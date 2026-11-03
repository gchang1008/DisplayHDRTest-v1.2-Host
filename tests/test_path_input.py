"""Read-only per-path DDC checks with isolated topology and backend."""
import subprocess
import http.client
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from test_display_ports import MultiController, Renderer
import displayhdr_monitor_input as native
import displayhdr_ports as ports


class PathReadTests(unittest.TestCase):
    def setUp(self):
        self.controller = MultiController()
        self.query = self.controller.query
        def query(flags):
            result = self.query(flags)
            for path in result.paths:
                path.source.id = path.target.id
            return result
        self.display = SimpleNamespace(query=query, device_path=self.controller.api.device_path,
            dll=SimpleNamespace(DisplayConfigGetDeviceInfo=lambda packet: 0))
        self.ddc = Mock()
        self.ddc.read.return_value = {"ok": True, "currentValue": 26}
        self.target = "00000000:00000063/2"

    def test_native_read_selects_requested_active_path_without_writing(self):
        result = native.query_input(self.display, self.ddc, read=(self.target, "monitor-2"))
        self.assertEqual(result["targetKey"], self.target)
        self.assertEqual(result["monitorDevicePath"], "monitor-2")
        self.ddc.read.assert_called_once()
        self.ddc.write.assert_not_called()
        self.assertEqual(self.controller.active_ids, [1, 2])

    def test_native_rejects_stale_identity_and_mirrored_source(self):
        with self.assertRaises(native.InputIdentityError):
            native.query_input(self.display, self.ddc, read=(self.target, "wrong"))
        self.display.query = self.query
        with self.assertRaises(native.InputIdentityError):
            native.query_input(self.display, self.ddc, read=(self.target, "monitor-2"))
        self.ddc.read.assert_not_called()

    def test_native_detects_topology_change_during_read(self):
        def changed(device):
            self.controller.active_ids = [2]
            return {"ok": True, "currentValue": 26}
        self.ddc.read.side_effect = changed
        with self.assertRaises(native.InputIdentityError):
            native.query_input(self.display, self.ddc, read=(self.target, "monitor-2"))
        self.ddc.write.assert_not_called()

    def test_native_write_still_requires_one_output(self):
        with self.assertRaises(native.InputIdentityError):
            native.query_input(self.display, self.ddc, write=(self.target, "monitor-2", 18))
        self.ddc.write.assert_not_called()

    def test_path_worker_has_three_second_bound_and_no_retry(self):
        with patch.object(native.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 3)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                native.read_native(self.target, "monitor-2")
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(run.call_args.args[0][-3:], ["--read", self.target, "monitor-2"])


class PathServiceTests(unittest.TestCase):
    def setUp(self):
        self.controller, self.renderer = MultiController(), Renderer()
        self.read = Mock(return_value={"ok": True, "currentValue": 26,
            "targetKey": "00000000:00000063/2", "monitorDevicePath": "monitor-2"})
        self.writer = Mock()
        self.service = ports.DisplayPortService(self.renderer, lambda: self.controller,
            input_writer=self.writer, path_input_reader=self.read)
        self.addCleanup(self.service.close)
        self.request = dict(version=1, id="read-1", command="read_display_input",
            targetKey="00000000:00000063/2", monitorDevicePath="monitor-2")

    def test_multiple_output_read_requires_no_interrupt_and_changes_nothing(self):
        result = self.service.dispatch(self.request)
        self.assertEqual(result["currentValue"], 26)
        self.assertTrue(self.service.status()["pathInputQuerySupported"])
        self.assertEqual(self.controller.active_ids, [1, 2])
        self.assertEqual(self.controller.trials, [])
        self.assertEqual(self.renderer.restart_count, 0)
        self.writer.assert_not_called()
        self.assertNotIn("read_display_input", __import__("displayhdr_server").MUTATION_COMMANDS)

    def test_inactive_identity_and_extra_fields_are_rejected(self):
        for extra in ({"targetKey": "00000000:00000063/3", "monitorDevicePath": "monitor-3"},
                      {"monitorDevicePath": "wrong"}, {"allowInterrupt": True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.service.dispatch({**self.request, **extra})
        self.read.assert_not_called()
        self.assertEqual(self.controller.trials, [])

    def test_changed_topology_or_wrong_reader_identity_is_rejected(self):
        self.read.return_value["monitorDevicePath"] = "wrong"
        with self.assertRaises(ValueError):
            self.service.dispatch(self.request)
        self.assertEqual(self.controller.active_ids, [1, 2])
        self.writer.assert_not_called()

    def test_service_rechecks_topology_after_read(self):
        def changed(*args):
            self.controller.active_ids = [2]
            return dict(ok=True, currentValue=26, targetKey=self.request["targetKey"], monitorDevicePath="monitor-2")
        self.read.side_effect = changed
        with self.assertRaises(ValueError):
            self.service.dispatch(self.request)
        self.assertEqual(self.controller.trials, [])
        self.writer.assert_not_called()

    def test_http_read_returns_action_without_interrupt_permission(self):
        import displayhdr_server
        instance = displayhdr_server.create_server("127.0.0.1", 0, 123)
        instance.display_ports = self.service
        worker = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": .01})
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", instance.server_port, timeout=2)
        try:
            connection.request("POST", "/api", json.dumps(self.request), {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            result = json.loads(response.read())
            self.assertTrue(result["ok"])
            self.assertEqual(result["action"]["command"], "read_display_input")
            self.assertEqual(result["action"]["currentValue"], 26)
            self.assertEqual(self.controller.trials, [])
            self.writer.assert_not_called()
        finally:
            connection.close()
            instance.shutdown()
            instance.server_close()
            worker.join(2)
