"""Exercise the remote GUI with deterministic network responses."""
import copy
import os
from pathlib import Path
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from displayhdr_gui import RemoteWindow


class FakeClient:
    def __init__(self, url):
        self.url = url
        self.calls = []
        self.fail = False
        self.delay = .01
        self.state = {"test": {"id": "ColorPatches", "title": "6. Checking Red"},
                      "settings": {"color": "Red", "textVisible": True},
                      "effective": {"nits": None}, "timing": {}, "presentation": {"submitted": True}}

    def request(self, command, **fields):
        self.calls.append((command, fields))
        time.sleep(self.delay)
        if self.fail:
            raise TimeoutError("test timeout")
        if command == "catalog":
            return {"ok": True, "catalog": {"tests": [{"id": "ColorPatches", "title": "6. Checking"}]}}
        if command == "key":
            self.state["lastSetRequestId"] = "fake-1"
            if fields["key"] == "Space":
                self.state["settings"]["textVisible"] = not self.state["settings"]["textVisible"]
        return {"ok": True, "id": "fake-1", "state": copy.deepcopy(self.state)}


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition, timeout=3):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            QTest.qWait(10)
        self.assertTrue(condition())

    def setUp(self):
        self.window = RemoteWindow(FakeClient)
        self.window.show()
        self.window.activateWindow()
        self.window.host.setText("127.0.0.1")
        self.window.connect_host()
        self.wait(lambda: self.window.connected and not self.window.busy)
        self.window.poll.stop()
        self.client = self.window.client
        self.client.calls.clear()

    def tearDown(self):
        self.window.close()
        QTest.qWait(30)

    def keys(self):
        return [fields["key"] for command, fields in self.client.calls if command == "key"]

    def test_buttons_and_state_readback(self):
        for key in self.window.buttons:
            QTest.mouseClick(self.window.buttons[key], Qt.MouseButton.LeftButton)
            self.wait(lambda: not self.window.busy)
        self.assertEqual(set(self.keys()), set(self.window.buttons))
        self.assertIn('"textVisible": false', self.window.details.toPlainText())
        self.assertIn("6. Checking", self.window.title.text())

    def test_keyboard_release_and_shift_jump(self):
        QTest.keyPress(self.window, Qt.Key.Key_Space)
        self.assertEqual(self.keys(), [])
        QTest.keyRelease(self.window, Qt.Key.Key_Space)
        self.wait(lambda: not self.window.busy)
        QTest.keyClick(self.window, Qt.Key.Key_1, Qt.KeyboardModifier.ShiftModifier)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.keys(), ["Space", "Shift+1"])

    def test_control_combination_does_not_toggle_subtitles(self):
        QTest.keyClick(self.window, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(40)
        self.assertEqual(self.keys(), [])
        QTest.keyClick(self.window, Qt.Key.Key_Control)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.keys(), ["Control"])

    def test_input_focus_does_not_control_host(self):
        self.window.host.setFocus()
        QTest.keyClick(self.window.host, Qt.Key.Key_C)
        QTest.keyClick(self.window.host, Qt.Key.Key_Space)
        QTest.qWait(30)
        self.assertEqual(self.keys(), [])

    def test_keyboard_shift_arrows_and_interval(self):
        QTest.keyPress(self.window, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
        QTest.qWait(660)
        QTest.keyRelease(self.window, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
        self.wait(lambda: not self.window.busy)
        self.assertGreaterEqual(len(self.keys()), 2)
        self.assertEqual(set(self.keys()), {"Shift+Up"})
        QTest.keyClick(self.window, Qt.Key.Key_Plus, Qt.KeyboardModifier.ShiftModifier)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.keys()[-1], "Shift+Plus")

    def test_hold_repeats_and_stops_without_queue(self):
        self.window.shift.setChecked(True)
        QTest.mousePress(self.window.buttons["Up"], Qt.MouseButton.LeftButton)
        QTest.qWait(660)
        QTest.mouseRelease(self.window.buttons["Up"], Qt.MouseButton.LeftButton)
        self.wait(lambda: not self.window.busy)
        count = len(self.keys())
        self.assertGreaterEqual(count, 2)
        self.assertEqual(set(self.keys()), {"Shift+Up"})
        QTest.qWait(250)
        self.assertEqual(len(self.keys()), count)
        self.client.delay = .15
        self.assertTrue(self.window.send_key("Space"))
        self.assertFalse(self.window.send_key("C"))
        self.wait(lambda: not self.window.busy)
        self.assertNotIn("C", self.keys())

    def test_timeout_disables_controls_and_never_replays(self):
        self.client.fail = True
        self.window.send_key("Space")
        self.wait(lambda: not self.window.busy)
        self.assertFalse(self.window.connected)
        self.assertFalse(self.window.controls.isEnabled())
        self.assertFalse(self.window.repeat.isActive())
        QTest.qWait(100)
        self.assertEqual(self.keys(), ["Space"])
        self.window.connect_host()
        self.wait(lambda: self.window.connected and not self.window.busy)
        self.assertEqual([c for c, _ in self.window.client.calls], ["catalog", "get_state"])

    def test_close_during_request_is_responsive(self):
        self.client.delay = .2
        self.window.send_key("Space")
        start = time.monotonic()
        self.window.close()
        self.assertLess(time.monotonic() - start, .1)
        QTest.qWait(250)
        self.assertFalse(self.window.poll.isActive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
