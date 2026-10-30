"""Isolated bridge/service checks; never changes the test computer's displays."""
import ctypes as C
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import displayhdr_display_paths as paths
import displayhdr_ports as ports
import displayhdr_server as server


class Controller:
    def __init__(self):
        self.current = 1
        self.trials, self.restores = [], []
        self.api = SimpleNamespace(query=self.query, device_path=lambda path: f"monitor-{path.target.id}",
                                   check=lambda code: None, dll=SimpleNamespace(DisplayConfigGetDeviceInfo=self.name))
        self.failure = None

    def row(self):
        return {"targetKey": f"00000000:00000063/{self.current}", "sourceKey": "00000000:00000063/0",
                "active": True, "available": True, "sourceMode": {}, "targetMode": {},
                "monitorDevicePath": f"monitor-{self.current}"}

    def query(self, flags):
        targets = (1, 2, 3) if flags == paths.QDC_ALL_PATHS else (self.current,)
        result = []
        for target in targets:
            path = paths.Path()
            path.source.adapter = path.target.adapter = paths.Luid(99, 0)
            path.target.id = target
            path.flags = path.target.available = 1
            path.target.technology = 5 if target == 2 else 10
            result.append(path)
        return SimpleNamespace(paths=result, modes=[])

    def name(self, packet):
        target = C.cast(packet, C.POINTER(paths.TargetName)).contents
        for i, char in enumerate("Test DUT"):
            target.name[i] = ord(char)
        return 0

    def inspect(self):
        return {"active": {"paths": [self.row()]}, "matchesDatabase": True}

    def trial(self, target, identity, hold, save_to_database):
        self.trials.append(target)
        self.current = int(target.rsplit("/", 1)[1])
        if self.failure:
            raise self.failure
        return {"switched": {"paths": [self.row()]}}



class Renderer:
    def __init__(self):
        self.process = 100
        self.test = "StartOfTest"
        self.hdr = True
        self.unavailable = False
        self.restart_error = None
        self.restart_count = 0
        self.managed = True

    def restart_supported(self):
        return self.managed

    def state(self):
        if self.unavailable:
            raise RuntimeError("renderer unavailable")
        return {"test": {"id": self.test}, "display": {"hdr": self.hdr},
                "settings": {"fullscreen": True, "color": "Blue", "textVisible": False},
                "presentation": {"presented": True, "resourcesValid": True}}

    def request(self, command, **fields):
        self.test = fields.get("test", self.test)
        return self.state()

    def catalog(self):
        return {"settingSchema": {}}

    def restart(self):
        self.restart_count += 1
        if self.restart_error:
            raise self.restart_error
        before, self.process = self.process, self.process + 1
        self.unavailable = False
        return {"pidBefore": before, "pid": self.process, "state": self.state()}

    def pid(self):
        return self.process


class PortTests(unittest.TestCase):
    def setUp(self):
        self.controller, self.renderer = Controller(), Renderer()
        self.input = Mock(return_value={"ok": True, "currentValue": 26,
            "targetKey": "00000000:00000063/1", "monitorDevicePath": "monitor-1"})
        self.writer = Mock(return_value={"accepted": True, "value": 18})
        self.hdr, self.window = Mock(), Mock()
        self.hdr.enable.return_value = {"changed": True}
        self.window.bring_front.return_value = {"unobstructed": True}
        self.service = ports.DisplayPortService(self.renderer, lambda: self.controller, self.input,
            lambda: self.hdr, lambda: self.window, self.writer)
        self.addCleanup(self.service.close)

    def action(self, command, target=1, identifier="op-1", **extra):
        return self.service.dispatch({"version": 1, "id": identifier, "command": command,
            "allowInterrupt": True, "targetKey": f"00000000:00000063/{target}",
            "monitorDevicePath": f"monitor-{target}", **extra})

    def test_output_selection_never_controls_renderer_hdr_ddc_or_window(self):
        self.renderer.test = "ColorPatchesFull"
        with patch.object(self.renderer, "request", side_effect=AssertionError("No screen control")):
            result = self.action("set_display_output", target=2)
        self.assertTrue(result["changed"])
        self.assertEqual(self.controller.current, 2)
        self.assertEqual(self.renderer.restart_count, 0)
        for method in (self.input, self.writer, self.hdr.enable, self.window.bring_front):
            method.assert_not_called()

    def test_same_output_is_noop(self):
        self.assertFalse(self.action("set_display_output")["changed"])
        self.assertEqual(self.controller.trials, [])

    def test_each_other_action_executes_only_requested_operation(self):
        for command, method, extra in (("write_display_input", self.writer, {"value": 18}),
                ("enable_display_hdr", self.hdr.enable, {}), ("present_display_window", self.window.bring_front, {})):
            with self.subTest(command=command):
                self.action(command, identifier=command, **extra)
                method.assert_called_once()
                self.assertEqual(self.controller.trials, [])
                self.assertEqual(self.renderer.restart_count, 0)
                self.input.assert_not_called()

    def test_wrong_identity_rejected_before_any_write(self):
        with self.assertRaises(ValueError):
            self.action("write_display_input", target=2, value=18)
        self.writer.assert_not_called()
        with self.assertRaises(ValueError):
            self.action("set_display_output", target=8, identifier="bad")
        self.assertEqual(self.controller.trials, [])

    def test_duplicate_id_is_not_replayed_and_changed_payload_rejected(self):
        first = self.action("write_display_input", value=18)
        self.assertEqual(first, self.action("write_display_input", value=18))
        self.writer.assert_called_once()
        with self.assertRaises(ValueError):
            self.action("write_display_input", value=15)

    def test_unknown_write_outcome_never_retried_or_followed_by_output_change(self):
        self.writer.side_effect = TimeoutError("unknown outcome")
        with self.assertRaises(TimeoutError):
            self.action("write_display_input", value=18)
        with self.assertRaises(ValueError):
            self.action("write_display_input", value=18)
        self.writer.assert_called_once()
        self.assertFalse(self.service.busy())
        self.assertEqual(self.controller.trials, [])

    def test_invalid_fields_busy_and_multiple_outputs_are_rejected(self):
        for extra in ({"allowInterrupt": False}, {"unexpected": True}):
            with self.assertRaises(ValueError):
                self.action("set_display_output", **extra)
        self.service.running = True
        with self.assertRaises(ValueError):
            self.action("set_display_output")
        self.service.running = False
        with patch.object(self.controller, "inspect", return_value={"active": {"paths": []}, "matchesDatabase": True}):
            with self.assertRaises(ValueError):
                self.action("set_display_output", identifier="bad-layout")

    def test_passive_inventory_skips_all_ddc_and_has_client_capability(self):
        result = self.service.inventory("passive")
        self.input.assert_not_called()
        self.writer.assert_not_called()
        self.assertEqual(result["controlOwner"], "client")
        self.assertTrue(result["manualSupported"])

    def test_legacy_workflow_is_not_available(self):
        for command in ("switch_display_port", "prepare_display_test"):
            with self.assertRaises(ValueError):
                self.action(command)


class NativeWriteTests(unittest.TestCase):
    def test_write_validates_identity_and_sends_only_source_value(self):
        import displayhdr_monitor_input as native
        controller = Controller()
        display = SimpleNamespace(query=controller.query, device_path=controller.api.device_path,
            dll=SimpleNamespace(DisplayConfigGetDeviceInfo=lambda packet: 0))
        ddc = Mock()
        ddc.write.return_value = {"accepted": True, "value": 18}
        with self.assertRaises(native.InputIdentityError):
            native.query_input(display=display, ddc=ddc, write=("wrong", "monitor-1", 18))
        ddc.write.assert_not_called()
        result = native.query_input(display=display, ddc=ddc, write=("00000000:00000063/1", "monitor-1", 18))
        self.assertTrue(result["accepted"])
        ddc.write.assert_called_once_with("", 18)
        ddc.read.assert_not_called()

    def test_write_worker_has_bound_and_never_retries_unknown_result(self):
        import displayhdr_monitor_input as native
        with patch.object(native.subprocess, "run", side_effect=subprocess.TimeoutExpired("native", 3)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                native.write_native("target", "identity", 18)
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(run.call_args.args[0][-4:], ["--write", "target", "identity", "18"])
        with patch.object(native.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b'{"accepted":false,"error":"unsupported"}')):
            with self.assertRaisesRegex(RuntimeError, "unsupported"):
                native.write_native("target", "identity", 18)


class PathSelectionTests(unittest.TestCase):
    def test_manual_selection_without_checkpoint_never_restores_even_after_apply_error(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                current = [1]
                calls = []

                def snapshot(ids):
                    rows = []
                    for target in ids:
                        row = paths.Path()
                        row.source.adapter = row.target.adapter = paths.Luid(99, 0)
                        row.target.id = target
                        row.flags = row.target.available = 1
                        rows.append(row)
                    return paths.Snapshot(rows, [])

                def query(flags):
                    return snapshot((1, 2) if flags == paths.QDC_ALL_PATHS else current)

                def apply(proposal, flags):
                    calls.append(flags)
                    if flags & paths.SDC_APPLY:
                        current[:] = [proposal.paths[0].target.id]
                        if fail:
                            raise RuntimeError("Apply confirmation failed")

                api = SimpleNamespace(query=query, set=apply,
                    device_path=lambda row: f"monitor-{row.target.id}")
                capture = lambda value: {"paths": [{"sourceMode": {}, "targetMode": {}} for row in value.paths]}
                with patch.object(paths, "describe", side_effect=capture), patch.object(paths, "equivalent_paths", return_value=True):
                    controller = paths.DisplayPaths(api)
                    if fail:
                        with self.assertRaises(paths.TrialError):
                            controller.trial("00000000:00000063/2", "monitor-2", None, save_to_database=True)
                    else:
                        result = controller.trial("00000000:00000063/2", "monitor-2", None, save_to_database=True)
                        self.assertFalse(result["restored"])
                self.assertEqual(current, [2])
                self.assertEqual(len(calls), 2)
                self.assertTrue(calls[1] & paths.SDC_SAVE_TO_DATABASE)


class PortHttpTests(unittest.TestCase):
    def test_native_timeout_reports_unknown_outcome_without_repeating(self):
        instance = server.create_server("127.0.0.1", 0, 123)
        service = Mock()
        service.dispatch.side_effect = subprocess.TimeoutExpired("native", 3)
        instance.display_ports = service
        worker = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": .01})
        worker.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", instance.server_port, timeout=2)
            connection.request("POST", "/api", json.dumps({"version": 1, "id": "once", "command": "write_display_input",
                "targetKey": "target", "monitorDevicePath": "identity", "allowInterrupt": True, "value": 18}),
                {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 504)
            self.assertTrue(json.loads(response.read())["error"]["requestMayHaveApplied"])
            service.dispatch.assert_called_once()
            connection.close()
        finally:
            instance.shutdown(); instance.server_close(); worker.join(2)

    def test_status_works_without_renderer_and_mutations_are_not_forwarded_when_busy(self):
        instance = server.create_server("127.0.0.1", 0, 123)
        service = Mock()
        service.busy.return_value = True
        service.dispatch.return_value = {"operation": {"phase": "running"}}
        instance.display_ports = service
        thread = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        try:
            for command, expected in (("get_display_port_status", 200), ("set_state", 409), ("restart_host", 409)):
                connection = http.client.HTTPConnection("127.0.0.1", instance.server_port, timeout=2)
                try:
                    body = json.dumps({"version": 1, "id": command, "command": command})
                    connection.request("POST", "/api", body, {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    result = json.loads(response.read())
                    self.assertEqual(result["ok"], expected == 200)
                finally:
                    connection.close()
        finally:
            instance.shutdown()
            instance.server_close()
            thread.join(2)
