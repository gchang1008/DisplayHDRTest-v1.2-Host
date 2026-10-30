"""Window focus verification with isolated Win32 fixtures; no desktop changes."""
import ctypes as C
import json
import subprocess
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from displayhdr_window_presentation import HOST_CLASS, GuiThreadInfo, NativeWindowApi, WindowPresentation


class WindowApi:
    def __init__(self):
        self.calls = []
        self.accept = True
        self.focus = True
        self.focus_error = False
        self.is_foreground = True
        self.cloaked = False

    def coordinates(self):
        return nullcontext()

    def windows(self):
        return [10]

    def identity(self, hwnd):
        return 99, HOST_CLASS

    def info(self, hwnd, client=False):
        return dict(visible=True, minimized=False, cloaked=self.cloaked,
                    topmost=True, clientRect=[0, 0, 100, 100])

    def above(self, hwnd):
        return []

    def foreground(self):
        return 10 if self.is_foreground else 20

    def keyboard_focused(self, hwnd):
        if self.focus_error:
            raise OSError("focus query failed")
        return self.focus

    def raise_window(self, hwnd):
        self.calls.append("raise")

    def pin_window(self, hwnd):
        self.calls.append("pin")

    def set_foreground(self, hwnd):
        self.calls.append("focus")
        return self.accept


class WindowFocusTests(unittest.TestCase):
    def test_focus_is_requested_after_pin_and_actual_state_is_returned(self):
        api = WindowApi()
        result = WindowPresentation(api).bring_front(99, keep_on_top=True)
        self.assertEqual(api.calls, ["raise", "pin", "focus"])
        self.assertTrue(result["unobstructed"])
        self.assertTrue(result["foreground"])
        self.assertTrue(result["keyboardFocused"])

    def test_topmost_is_distinct_from_foreground_and_keyboard_focus(self):
        api = WindowApi()
        api.accept = api.is_foreground = api.focus = False
        result = WindowPresentation(api).bring_front(99, keep_on_top=True)
        self.assertTrue(result["topmost"])
        self.assertTrue(result["unobstructed"])
        self.assertFalse(result["foreground"])
        self.assertFalse(result["keyboardFocused"])
        self.assertFalse(result["foregroundRequestAccepted"])

    def test_focus_query_failure_is_reported_and_cannot_pass_inspection(self):
        api = WindowApi()
        api.focus_error = True
        result = WindowPresentation(api).bring_front(99, keep_on_top=True)
        self.assertFalse(result["keyboardFocused"])
        self.assertFalse(result["unobstructed"])
        self.assertIn("focus query failed", result["inspectionErrors"][0])

    def native(self):
        api = NativeWindowApi.__new__(NativeWindowApi)
        api.u = Mock()
        api.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 7)
        api.u.GetWindowThreadProcessId.return_value = 9
        api.u.GetForegroundWindow.return_value = 0
        api.u.AttachThreadInput.return_value = 1
        api.u.SetForegroundWindow.side_effect = [0, 1]
        return api

    def test_native_acquisition_detaches_target_input_queue(self):
        api = self.native()
        self.assertTrue(api.set_foreground(10))
        self.assertEqual([c.args for c in api.u.AttachThreadInput.call_args_list], [(7, 9, True), (7, 9, False)])
        api.u.SetFocus.assert_called_once_with(10)

    def test_native_acquisition_detaches_even_when_focus_request_fails(self):
        api = self.native()
        api.u.SetFocus.side_effect = OSError("focus denied")
        with self.assertRaisesRegex(OSError, "focus denied"):
            api.set_foreground(10)
        self.assertEqual(api.u.AttachThreadInput.call_args_list[-1].args, (7, 9, False))

    def test_native_already_focused_does_not_attach_input_queue(self):
        api = self.native()
        api.u.GetForegroundWindow.return_value = 10
        api.keyboard_focused = lambda hwnd: True
        api.set_foreground(10)
        api.u.AttachThreadInput.assert_not_called()
        api.u.SetFocus.assert_not_called()

    def test_native_focus_read_uses_target_gui_thread(self):
        api = self.native()
        def query(thread, pointer):
            self.assertEqual(thread, 9)
            info = C.cast(pointer, C.POINTER(GuiThreadInfo)).contents
            self.assertEqual(info.cbSize, C.sizeof(GuiThreadInfo))
            info.hwndFocus = 10
            return 1
        api.u.GetGUIThreadInfo.side_effect = query
        self.assertTrue(api.keyboard_focused(10))
        self.assertFalse(api.keyboard_focused(20))

    def test_foreground_and_target_threads_are_detached_in_reverse_order(self):
        api = self.native()
        api.u.GetForegroundWindow.return_value = 20
        api.u.GetWindowThreadProcessId.side_effect = lambda hwnd, pid: 11 if hwnd == 20 else 9
        self.assertTrue(api.set_foreground(10))
        self.assertEqual([c.args for c in api.u.AttachThreadInput.call_args_list],
                         [(7, 11, True), (7, 9, True), (7, 9, False), (7, 11, False)])

    def test_partial_attachment_failure_detaches_previous_thread(self):
        api = self.native()
        api.u.GetForegroundWindow.return_value = 20
        api.u.GetWindowThreadProcessId.side_effect = lambda hwnd, pid: 11 if hwnd == 20 else 9
        api.u.AttachThreadInput.side_effect = [1, 0, 1]
        def check(value):
            if not value:
                raise OSError("attach failed")
        api.check = check
        with self.assertRaisesRegex(OSError, "attach failed"):
            api.set_foreground(10)
        self.assertEqual(api.u.AttachThreadInput.call_args_list[-1].args, (7, 11, False))
        api.u.SetFocus.assert_not_called()

    def test_focus_failure_detaches_both_foreground_and_target(self):
        api = self.native()
        api.u.GetForegroundWindow.return_value = 20
        api.u.GetWindowThreadProcessId.side_effect = lambda hwnd, pid: 11 if hwnd == 20 else 9
        api.u.SetFocus.side_effect = OSError("focus failed")
        with self.assertRaisesRegex(OSError, "focus failed"):
            api.set_foreground(10)
        self.assertEqual([c.args for c in api.u.AttachThreadInput.call_args_list][-2:],
                         [(7, 9, False), (7, 11, False)])

    def test_worker_has_five_second_timeout_and_verified_pid(self):
        result = dict(pid=99, foreground=True, keyboardFocused=True, topmost=True, unobstructed=True)
        with patch("displayhdr_window_presentation.NativeWindowApi"), patch(
                "displayhdr_window_presentation.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=json.dumps(result))) as run:
            self.assertEqual(WindowPresentation().bring_front(99, keep_on_top=True), result)
            self.assertEqual(run.call_args.kwargs["timeout"], 5)
            self.assertEqual(run.call_args.args[0][-3:], ["--pid", "99", "--keep-on-top"])
            self.assertEqual(run.call_count, 1)

    def test_worker_timeout_is_not_retried(self):
        with patch("displayhdr_window_presentation.NativeWindowApi"), patch(
                "displayhdr_window_presentation.subprocess.run",
                side_effect=subprocess.TimeoutExpired("worker", 5)) as run:
            with self.assertRaisesRegex(TimeoutError, "timed out after 5 seconds"):
                WindowPresentation().bring_front(99)
            self.assertEqual(run.call_count, 1)

    def test_worker_rejects_wrong_pid_or_reports_native_error(self):
        for returncode, result in ((0, {"pid": 100}), (1, {"error": "focus denied"})):
            with patch("displayhdr_window_presentation.NativeWindowApi"), patch(
                    "displayhdr_window_presentation.subprocess.run",
                    return_value=SimpleNamespace(returncode=returncode, stdout=json.dumps(result))):
                with self.assertRaises(RuntimeError):
                    WindowPresentation().bring_front(99)
