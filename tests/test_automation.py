"""Exercise the real JSON/pipe/control code in the offscreen C++ test harness."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from displayhdr_api import DisplayHDRClient


class AutomationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exe = Path(os.environ["LOCALAPPDATA"]) / "DisplayHDRAutomationBuild/automation-x64-Release/harness/bin/RuntimeHarness.exe"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        cls.process = subprocess.Popen([str(exe)], cwd=exe.parent, startupinfo=startup,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            cls.client = DisplayHDRClient(cls.process.pid, 5)
        except Exception:
            cls.process.terminate()
            _, error = cls.process.communicate(timeout=10)
            raise RuntimeError(error.decode(errors="replace"))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        user = ctypes.WinDLL("user32")
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def close_window(window, _):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            if pid.value == cls.process.pid:
                user.PostMessageW(window, 0x10, 0, 0)
            return True

        user.EnumWindows(close_window, 0)
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.terminate()
            cls.process.wait(timeout=5)
            raise AssertionError("Server did not shut down cleanly.")
        if cls.process.returncode != 0:
            raise AssertionError(cls.process.stderr.read().decode(errors="replace"))
        cls.process.stderr.close()

    def state(self, **fields):
        response = self.client.request("set_state" if fields else "get_state", **fields)
        self.assertTrue(response["ok"], response)
        return response["state"]

    def test_all_tests_selectable(self):
        response = self.client.request("catalog")
        self.assertTrue(response["ok"])
        tests = response["catalog"]["tests"]
        self.assertEqual(len(tests), 47)
        self.assertEqual(len({t["id"] for t in tests}), 47)
        for test in tests:
            with self.subTest(test=test["id"]):
                state = self.state(test=test["id"], settings={"textVisible": False})
                self.assertEqual(state["test"]["id"], test["id"])
                self.assertTrue(state["presentation"]["applied"])
                self.assertTrue(state["presentation"]["submitted"])
                self.assertFalse(state["presentation"]["presented"])

    def test_every_persistent_setting_roundtrips(self):
        settings = {
            "textVisible": False, "subtitlesVisible": False, "paused": True, "fullscreen": False,
            "color": "Blue", "testingTier": 1000, "checkerboard": "4x3-inverted", "whiteLevel": 500,
            "blackIndex": 4, "profileIndex": 3, "xriteIndex": 97, "xriteAuto": False, "xriteInterval": 2.5,
            "dimmingMode": "2D", "gradient": {"r": .1, "g": .2, "b": .3},
            "staticContrastPq": 400, "staticContrastSrgb": 128, "activeDimmingPq": 451,
            "activeDimmingDarkPq": 240, "calibrationMaxPq": 700, "calibrationFullFramePq": 650,
            "calibrationMinPq": 10, "calibrationMaxSrgb": 220, "calibrationFullFrameSrgb": 200,
            "calibrationMinSrgb": 1,
        }
        state = self.state(test="ActiveDimming", settings=settings)
        self.assertEqual(set(settings), set(state["settings"]))
        for key, expected in settings.items():
            with self.subTest(setting=key):
                actual = state["settings"][key]
                if isinstance(expected, float):
                    self.assertAlmostEqual(actual, expected, places=5)
                elif isinstance(expected, dict):
                    for channel, value in expected.items():
                        self.assertAlmostEqual(actual[channel], value, places=5)
                else:
                    self.assertEqual(actual, expected)

    def test_blind_rgbw_selection_in_both_modes(self):
        for test in ("ColorPatches", "ColorPatchesFull"):
            for color in ("Blue", "Red", "White", "Green", "Blue"):
                state = self.state(test=test, settings={"color": color})
                self.assertEqual(state["settings"]["color"], color)
                self.assertIn(color, state["test"]["title"])
                self.assertEqual(state["effective"]["patchAreaFraction"], .08 if test == "ColorPatches" else 1)

    def test_overloaded_color_controls_report_correct_levels(self):
        for test, levels in (("SharpeningFilter", (80, 160, 240, 320)),
                             ("ToneMapSpike", (350, 700, 1015, 10000))):
            for color, nits in zip(("Red", "Green", "Blue", "White"), levels):
                state = self.state(test=test, settings={"color": color})
                self.assertEqual(state["effective"]["nits"], nits)
                self.assertNotIn("whiteLevel", state["applicableSettings"])
        state = self.state(test="ColorPatchesMAX")
        self.assertIsNone(state["effective"]["nits"])
        self.assertEqual(state["effective"]["referenceWhitePq"], 636)

    def test_requested_examples(self):
        state = self.state(test="ActiveDimming", settings={"nits": 49.79, "textVisible": True}, id="nits-example")
        self.assertEqual(state["test"]["title"], "5.1 Active Dimming")
        self.assertAlmostEqual(state["effective"]["nits"], 49.79, delta=.002)
        self.assertEqual(state["lastSetRequestId"], "nits-example")
        state = self.state(test="SubTitleFlicker", settings={"subtitlesVisible": False, "textVisible": False})
        self.assertEqual(state["test"]["title"], "1.2.4 Subtitle Flicker Test:")
        self.assertFalse(state["settings"]["subtitlesVisible"])
        self.assertFalse(state["settings"]["textVisible"])

    def test_invalid_request_is_atomic(self):
        before = self.state(test="ActiveDimming", settings={"color": "Red", "activeDimmingPq": 451})
        bad = self.client.request("set_state", test="ColorPatchesFull", settings={"color": "Blue", "blackIndex": 99})
        self.assertFalse(bad["ok"])
        after = self.state()
        self.assertEqual(before["test"], after["test"])
        self.assertEqual(before["settings"], after["settings"])
        self.assertEqual(before["stateVersion"], after["stateVersion"])
        for fields in ({"test": "invalid"}, {"settings": {"paused": "false"}},
                       {"settings": {"xriteInterval": 0}}, {"settings": {"unknown": 1}},
                       {"settings": {"profileIndex": 44.5}}, {"settings": {"gradient": {"r": 1}}}):
            self.assertFalse(self.client.request("set_state", **fields)["ok"])

    def test_xrite_initialization_does_not_override_requested_settings(self):
        self.state(test="StartOfTest")
        state = self.state(test="XRiteColors", settings={"xriteAuto": True, "xriteInterval": 2.5, "xriteIndex": 42})
        self.assertTrue(state["settings"]["xriteAuto"])
        self.assertEqual(state["settings"]["xriteIndex"], 42)
        self.assertAlmostEqual(state["timing"]["remainingSeconds"], 2.5, delta=.02)
        time.sleep(.12)
        repeated = self.state(settings={"xriteAuto": True, "xriteInterval": 2.5})
        self.assertLess(repeated["timing"]["remainingSeconds"], 2.45)
        self.state(settings={"xriteAuto": False})

    def test_automatic_state_updates_are_queryable(self):
        self.state(test="StartOfTest")
        first = self.state(test="XRiteColors", settings={"xriteAuto": True, "xriteInterval": .05, "xriteIndex": 10})
        time.sleep(.18)
        later = self.state()
        self.assertNotEqual(first["settings"]["xriteIndex"], later["settings"]["xriteIndex"])
        self.assertGreater(later["stateVersion"], first["stateVersion"])
        self.assertGreater(later["presentation"]["frameId"], first["presentation"]["frameId"])
        self.state(settings={"xriteAuto": False})

    def test_wait_conditions_are_separate_from_submission(self):
        state = self.state(test="WarmUp", restart=True)
        self.assertTrue(state["presentation"]["submitted"])
        self.assertFalse(state["timing"]["waitComplete"])
        self.assertAlmostEqual(state["timing"]["remainingSeconds"], 1800, delta=.05)
        time.sleep(.12)
        repeated = self.state(test="WarmUp")
        self.assertLess(repeated["timing"]["remainingSeconds"], 1799.95)
        restarted = self.state(test="WarmUp", restart=True)
        self.assertGreater(restarted["timing"]["remainingSeconds"], repeated["timing"]["remainingSeconds"])

    def test_protocol_errors_and_reconnection(self):
        self.assertFalse(self.client.send({"version": 2, "id": "wrong-version", "command": "get_state"})["ok"])
        self.assertFalse(self.client.request("unknown_command")["ok"])
        self.assertFalse(self.client.request("get_state", settings={})["ok"])
        self.client.close()
        type(self).client = DisplayHDRClient(self.process.pid)
        self.assertTrue(self.client.request("get_state")["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
