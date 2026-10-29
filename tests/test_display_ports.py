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

    def restart(self):
        self.restart_count += 1
        if self.restart_error:
            raise self.restart_error
        before, self.process = self.process, self.process + 1
        self.unavailable = False
        return {"pidBefore": before, "pid": self.process, "state": self.state()}

    def pid(self):
        return self.process


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class PortTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.controller, self.renderer = Controller(), Renderer()
        self.input = Mock(side_effect=self.read_input)
        self.hdr = Mock()
        self.hdr.enable.return_value = {"changed": False}
        self.window = Mock()
        self.window.bring_front.return_value = {"unobstructed": True}
        self.service = ports.DisplayPortService(self.renderer, lambda: self.controller,
                                                self.input, lambda: self.hdr, lambda: self.window)
        self.addCleanup(self.service.close)
        self.patches = [patch.object(ports.time, "sleep"), patch.object(ports.threading, "Thread", ImmediateThread)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def read_input(self):
        value = {1: 26, 2: 18, 3: 15}[self.controller.current]
        return {"ok": True, "currentValue": value, "currentRaw": value * 257,
                "targetKey": self.controller.row()["targetKey"], "monitorDevicePath": f"monitor-{self.controller.current}"}

    def request(self, command, identifier="op-1", **fields):
        return {"version": 1, "id": identifier, "command": command, **fields}

    def switch(self, target=2, identifier="op-1", calibration=False, **fields):
        return self.service.dispatch(self.request("switch_display_port", identifier,
            targetKey=f"00000000:00000063/{target}", monitorDevicePath=f"monitor-{target}",
            expectedInput=None if calibration or fields.get("verificationMode") == "manual" else {1: 26, 2: 18, 3: 15}[target], calibration=calibration,
            allowInterrupt=True, autoSwitchConfirmed=True, **fields))

    def test_returns_running_then_cached_ready_without_backup(self):
        initial = self.switch()
        self.assertEqual(initial["operation"]["phase"], "running")
        result = self.service.status()
        self.assertEqual(result["operation"]["phase"], "ready")
        self.assertEqual(result["operation"]["inputValue"], 18)
        self.assertEqual(result["operation"]["verificationMode"], "ddc")
        self.assertTrue(result["operation"]["inputVerified"])
        self.assertFalse(result["pendingRestore"])
        self.assertFalse((Path(self.folder.name) / "pending-display-restore.json").exists())
        self.assertFalse(self.service.busy())
        calls = self.input.call_count
        self.service.dispatch(self.request("get_display_port_status"))
        self.assertEqual(self.input.call_count, calls)

    def test_manual_mode_requires_explicit_choice_and_never_verifies_input(self):
        self.input.side_effect = OSError("DDC unavailable")
        inventory = self.service.inventory()
        self.assertFalse(inventory["supported"])
        self.assertTrue(inventory["manualSupported"])
        self.switch()
        self.assertEqual(self.service.status()["operation"]["phase"], "failed")
        self.assertEqual(self.controller.trials, [])
        with patch.object(self.service, "wait_input", side_effect=AssertionError("Manual mode must not poll input")):
            calls = self.input.call_count
            self.switch(identifier="manual", verificationMode="manual")
        result = self.service.status()
        operation = result["operation"]
        self.assertEqual(operation["phase"], "ready")
        self.assertTrue(operation["ready"])
        self.assertEqual(operation["verificationMode"], "manual")
        self.assertFalse(operation["inputVerified"])
        self.assertIsNone(operation["inputValue"])
        self.assertFalse(result["input"]["ok"])
        self.assertIsNone(result["input"]["currentValue"])
        self.assertEqual(self.input.call_count, calls + 1)
        self.assertEqual(self.controller.current, 2)
        self.assertTrue(operation["hdr"])
        self.assertTrue(operation["window"]["unobstructed"])

    def test_ddc_timeout_reports_unavailable_only_for_missing_input(self):
        for reading, unavailable in (({"ok": False, "error": "DDC unavailable"}, True),
                                     ({"ok": True, "currentValue": 15}, False),
                                     ({"ok": False, "identityMismatch": True}, False)):
            error = TimeoutError("Input query timed out")
            error.input_samples, error.last_input = [reading], reading
            with patch.object(self.service, "wait_input", side_effect=error):
                self.switch(identifier=str(reading))
            self.assertEqual(self.service.status()["operation"]["phase"], "failed")
            self.assertEqual(self.service.status()["operation"]["inputUnavailable"], unavailable)

    def test_manual_same_active_pairing_does_not_promote_available_ddc_value(self):
        self.switch(1, calibration=True, verificationMode="manual")
        result = self.service.status()
        self.assertEqual(result["operation"]["phase"], "ready")
        self.assertIsNone(result["operation"]["inputValue"])
        self.assertFalse(result["operation"]["inputVerified"])
        self.assertEqual(self.controller.trials, [])
        refreshed = self.service.inventory()
        self.assertEqual(refreshed["input"]["currentValue"], 26)
        self.assertEqual(refreshed["operation"]["verificationMode"], "manual")
        self.assertFalse(refreshed["operation"]["inputVerified"])

    def test_manual_mode_rejects_wrong_display_identity(self):
        self.input.side_effect = lambda: {**self.read_input(), "monitorDevicePath": "different-display"}
        inventory = self.service.inventory()
        self.assertFalse(inventory["manualSupported"])
        self.switch(verificationMode="manual")
        self.assertEqual(self.controller.trials, [])
        self.assertIn("identity", self.service.status()["operation"]["error"])
        self.input.side_effect = OSError("DDC unavailable")
        request = self.request("switch_display_port", "wrong-target", targetKey="00000000:00000063/2",
            monitorDevicePath="different-display", expectedInput=None, calibration=True,
            verificationMode="manual", allowInterrupt=True, autoSwitchConfirmed=True)
        self.service.dispatch(request)
        self.assertEqual(self.controller.trials, [])
        self.assertIn("identity", self.service.status()["operation"]["error"])

    def test_native_identity_failure_is_not_treated_as_unavailable_ddc(self):
        from displayhdr_monitor_input import query_input
        with self.assertRaises(ports.InputIdentityError):
            query_input(display=SimpleNamespace(query=lambda flags: SimpleNamespace(paths=[])))
        self.input.side_effect = ports.InputIdentityError("More than one physical monitor")
        inventory = self.service.inventory()
        self.assertTrue(inventory["input"]["identityMismatch"])
        self.assertFalse(inventory["manualSupported"])
        self.switch(verificationMode="manual")
        self.assertEqual(self.controller.trials, [])
        self.assertEqual(self.service.status()["operation"]["phase"], "failed")
        self.assertIn("physical monitor", self.service.status()["operation"]["error"])

    def test_manual_mode_retains_database_hdr_and_obstruction_checks(self):
        self.input.side_effect = OSError("DDC unavailable")
        with patch.object(self.controller, "inspect", return_value={"active": {"paths": [self.controller.row()]},
                                                                  "matchesDatabase": False}):
            self.assertFalse(self.service.inventory()["manualSupported"])
            self.switch(verificationMode="manual")
        self.assertEqual(self.controller.trials, [])
        self.renderer.hdr = False
        self.switch(identifier="hdr-failure", verificationMode="manual")
        self.assertIn("HDR", self.service.status()["operation"]["error"])
        self.renderer.hdr = True
        self.window.bring_front.return_value = {"unobstructed": False}
        self.switch(identifier="window-failure", verificationMode="manual")
        self.assertIn("obscured", self.service.status()["operation"]["error"])
        self.assertFalse(self.service.status()["operation"]["ready"])

    def test_manual_mode_cannot_bypass_multiple_active_outputs(self):
        original = self.controller.api.query
        self.controller.api.query = lambda flags: original(paths.QDC_ALL_PATHS if flags == paths.QDC_ONLY_ACTIVE_PATHS else flags)
        self.assertFalse(self.service.inventory()["manualSupported"])
        with patch.object(self.controller, "inspect", return_value={"active": {"paths": [self.controller.row()] * 2},
                                                                  "matchesDatabase": True}):
            self.switch(verificationMode="manual")
        self.assertEqual(self.controller.trials, [])

    def test_verification_mode_fields_are_strict(self):
        base = self.request("switch_display_port", targetKey="00000000:00000063/2",
            monitorDevicePath="monitor-2", expectedInput=None, calibration=False,
            verificationMode="manual", allowInterrupt=True, autoSwitchConfirmed=True)
        for fields in ({"verificationMode": True}, {"verificationMode": "auto"},
                       {"verificationMode": None}, {"expectedInput": 18}, {"verificationMode": "ddc"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.service.dispatch({**base, **fields})
        self.assertEqual(self.controller.trials, [])

    def test_continuous_switch_uses_current_state_without_restoring(self):
        self.switch()
        self.switch(3, "op-2")
        self.assertEqual(len(self.controller.trials), 2)
        self.assertEqual(self.controller.current, 3)
        self.assertEqual(self.controller.restores, [])
        self.assertFalse(self.service.status()["pendingRestore"])

    def test_same_active_matching_does_not_apply_ccd_or_save_backup(self):
        self.switch(1, calibration=True)
        self.assertEqual(self.controller.trials, [])
        self.assertFalse(self.service.status()["pendingRestore"])
        self.assertEqual(self.service.status()["operation"]["inputValue"], 26)
        self.assertTrue(self.service.status()["operation"]["calibration"])

    def test_matching_and_switch_do_not_select_a_verification_pattern(self):
        with patch.object(self.renderer, "request", wraps=self.renderer.request) as request:
            self.switch(1, calibration=True)
            self.switch(2, "op-2")
        self.assertEqual(request.call_args_list, [
            unittest.mock.call("set_state", test="StartOfTest", settings={"fullscreen": True}),
            unittest.mock.call("set_state", settings={"fullscreen": True, "textVisible": False}),
            unittest.mock.call("set_state", test="StartOfTest", settings={"fullscreen": True}),
            unittest.mock.call("set_state", settings={"fullscreen": True, "textVisible": False})])
        result = self.service.status()
        self.assertEqual(result["operation"]["phase"], "ready")
        self.assertTrue(result["operation"]["window"]["unobstructed"])
        self.assertEqual(self.window.bring_front.call_count, 2)
        self.window.bring_front.assert_called_with(self.renderer.pid(), keep_on_top=True)
        self.assertEqual(self.renderer.test, "StartOfTest")

    def test_obstruction_still_blocks_ready_without_restoring_output(self):
        self.window.bring_front.return_value = {"unobstructed": False}
        self.switch()
        result = self.service.status()
        self.assertEqual(result["operation"]["phase"], "failed")
        self.assertFalse(result["operation"]["ready"])
        self.assertIn("obscured", result["operation"]["error"])
        self.assertFalse(result["pendingRestore"])
        self.assertEqual(self.controller.current, 2)
        self.assertFalse(self.service.busy())

    def test_switch_still_requires_hdr_after_restart(self):
        self.renderer.hdr = False
        self.switch()
        self.assertEqual(self.service.status()["operation"]["phase"], "failed")
        self.assertIn("HDR mode", self.service.status()["operation"]["error"])
        self.assertFalse(self.service.status()["pendingRestore"])

    def test_failed_restart_can_recover_by_refreshing_current_state(self):
        self.renderer.restart_error = RuntimeError("restart failed")
        self.switch()
        self.assertEqual(self.service.status()["operation"]["phase"], "failed")
        self.assertEqual(self.controller.current, 2)
        self.renderer.restart_error = None
        self.service.inventory()
        self.assertEqual(self.service.status()["operation"]["phase"], "idle")
        self.switch(3, "op-2")
        self.assertEqual(self.service.status()["operation"]["phase"], "ready")
        self.assertEqual(self.controller.current, 3)
        self.assertEqual(self.controller.restores, [])

    def test_duplicate_request_cannot_apply_twice_or_change_payload(self):
        self.switch()
        self.switch()
        self.assertEqual(len(self.controller.trials), 1)
        with self.assertRaises(ValueError):
            self.switch(3)

    def reload(self):
        reloaded = ports.DisplayPortService(self.renderer, lambda: self.controller,
            self.input, lambda: self.hdr, lambda: self.window)
        self.addCleanup(reloaded.close)
        return reloaded

    def test_interrupted_operation_is_not_resumed_but_refresh_allows_new_switch(self):
        self.switch()
        self.service.data["operation"]["phase"] = "running"
        reloaded = self.reload()
        self.assertEqual(reloaded.status()["operation"]["phase"], "idle")
        self.assertFalse(reloaded.status()["pendingRestore"])
        self.assertEqual(len(self.controller.trials), 1)
        self.assertTrue(reloaded.inventory()["supported"])
        request = self.request("switch_display_port", "new", targetKey="00000000:00000063/3",
            monitorDevicePath="monitor-3", expectedInput=15, calibration=False,
            allowInterrupt=True, autoSwitchConfirmed=True)
        reloaded.dispatch(request)
        self.assertEqual(reloaded.status()["operation"]["phase"], "ready")
        self.assertEqual(self.controller.current, 3)

    def test_old_pending_file_is_ignored_without_deletion_or_restoration(self):
        self.switch()
        pending = Path(self.folder.name) / "pending-display-restore.json"
        pending.write_text("old recovery data")
        reloaded = self.reload()
        result = reloaded.status()
        self.assertEqual(result["operation"]["phase"], "idle")
        self.assertFalse(result["supported"])
        self.assertFalse(result["operation"]["ready"])
        self.assertNotIn("state", result["operation"])
        self.assertNotIn("window", result["operation"])
        self.assertFalse(result["pendingRestore"])
        self.assertTrue(reloaded.inventory()["supported"])
        self.assertEqual(reloaded.status()["operation"]["phase"], "idle")
        self.assertEqual(pending.read_text(), "old recovery data")
        self.assertEqual(self.controller.restores, [])

    def test_failed_input_refresh_does_not_clear_unconfirmed_operation(self):
        self.switch()
        self.service.data["operation"].update(phase="failed", ready=False)
        self.input.side_effect = RuntimeError("DDC unavailable")
        self.assertFalse(self.service.inventory()["supported"])
        self.assertEqual(self.service.status()["operation"]["phase"], "failed")

    def test_refresh_reports_identity_mismatch_without_clearing_failure(self):
        self.service.data["operation"].update(phase="failed", ready=False)
        self.input.side_effect = lambda: {**self.read_input(), "monitorDevicePath": "different-DUT"}
        result = self.service.inventory()
        self.assertFalse(result["supported"])
        self.assertIn("identity", result["error"])
        self.assertEqual(result["operation"]["phase"], "failed")

    def test_failed_apply_preserves_current_output_and_clears_busy(self):
        self.controller.failure = RuntimeError("apply verification failed")
        self.switch()
        self.assertEqual(self.controller.current, 2)
        self.assertEqual(self.controller.restores, [])
        self.assertEqual(self.service.status()["operation"]["phase"], "failed")
        self.assertFalse(self.service.busy())

    def test_thread_start_failure_does_not_leave_operation_busy(self):
        with patch.object(ports.threading, "Thread", side_effect=RuntimeError("Thread unavailable")):
            with self.assertRaises(RuntimeError):
                self.switch()
        self.assertFalse(self.service.busy())
        self.assertEqual(self.controller.trials, [])
        self.assertEqual(self.service.status()["operation"]["phase"], "failed")

    def test_removed_restore_command_is_rejected_without_mutation(self):
        self.assertNotIn("restore_display_ports", ports.COMMANDS)
        with self.assertRaises(ValueError):
            self.service.dispatch(self.request("restore_display_ports", allowInterrupt=True))
        self.assertEqual(self.controller.trials, [])
        self.assertEqual(self.controller.restores, [])

    def test_timeout_is_reported_by_inventory_and_can_recover_within_wait(self):
        self.input.side_effect = subprocess.TimeoutExpired("native-worker", 3)
        result = self.service.inventory()
        self.assertFalse(result["supported"])
        self.assertFalse(result["input"]["ok"])
        value = self.read_input()
        self.input.side_effect = [subprocess.TimeoutExpired("native-worker", 3), value, value]
        reading, samples = self.service.wait_input(value["targetKey"], "monitor-1", 26)
        self.assertEqual(reading["currentValue"], 26)
        self.assertFalse(samples[0]["matches"])

    def test_wait_timeout_does_not_accept_wrong_input(self):
        with patch.object(ports.time, "monotonic", side_effect=[0, 0, 46, 46]):
            with self.assertRaises(TimeoutError):
                self.service.wait_input(self.controller.row()["targetKey"], "monitor-1", 18)

    def test_calibration_excludes_a_stable_old_source_until_new_value_arrives(self):
        value = self.read_input()
        new = {**value, "currentValue": 18, "currentRaw": 0x1212}
        self.input.side_effect = [value, value, value, new, new]
        reading, samples = self.service.wait_input(value["targetKey"], "monitor-1", None, excluded=26)
        self.assertEqual(reading["currentValue"], 18)
        self.assertEqual([sample["matches"] for sample in samples], [False, False, False, True, True])
        with patch.object(ports.time, "monotonic", side_effect=[0, 0, 46, 46]):
            self.input.side_effect = self.read_input
            with self.assertRaises(TimeoutError):
                self.service.wait_input(value["targetKey"], "monitor-1", None, excluded=26)

    def test_service_rejects_concurrent_operation_without_file_lock(self):
        self.service.data["operation"]["phase"] = "running"
        with self.assertRaises(ValueError):
            self.switch()
        self.assertEqual(self.controller.trials, [])

    def test_input_service_does_not_read_or_write_files_or_create_directories(self):
        with patch.object(Path, "open", side_effect=AssertionError("File access")), patch.object(
                Path, "mkdir", side_effect=AssertionError("Directory creation")), patch(
                "builtins.open", side_effect=AssertionError("File access")):
            reloaded = self.reload()
            self.assertTrue(reloaded.inventory()["supported"])
            reloaded.dispatch(self.request("switch_display_port", targetKey="00000000:00000063/2",
                monitorDevicePath="monitor-2", expectedInput=18, calibration=False,
                allowInterrupt=True, autoSwitchConfirmed=True))
            self.assertEqual(reloaded.status()["operation"]["phase"], "ready")
            reloaded.close()
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_public_status_does_not_grow_with_diagnostic_history(self):
        self.service.data["operation"].update(inputSamples=[{"error": "x" * 10000}] * 100,
            selection={"rawCCD": "x" * 100000}, portRestart={"state": {"huge": "x" * 100000}})
        self.service.data["selectedConfiguration"] = {"huge": "x" * 100000}
        self.assertLess(len(json.dumps(self.service.status())), 2000)

    def test_measurement_and_attached_renderer_are_rejected_before_mutation(self):
        self.renderer.test = "Warmup"
        with self.assertRaises(ValueError):
            self.switch()
        self.renderer.test, self.renderer.managed = "StartOfTest", False
        with self.assertRaises(ValueError):
            self.switch()
        self.assertEqual(self.controller.trials, [])
        self.assertFalse(self.service.status()["pendingRestore"])

    def test_unknown_fields_and_wrong_types_are_rejected(self):
        request = self.request("switch_display_port", targetKey="x", monitorDevicePath="x",
                               expectedInput=True, calibration=False, allowInterrupt=True, autoSwitchConfirmed=True)
        with self.assertRaises(ValueError):
            self.service.dispatch(request)
        request["expectedInput"] = 18
        request["extra"] = True
        with self.assertRaises(ValueError):
            self.service.dispatch(request)


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
