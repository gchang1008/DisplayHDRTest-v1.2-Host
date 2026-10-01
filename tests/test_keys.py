"""Verify remote key semantics through HTTP and the original Game handlers."""
import sys
from pathlib import Path
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import test_automation
from displayhdr_remote import DisplayHDRRemoteClient
from displayhdr_server import create_server


class KeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_automation.AutomationTests.setUpClass()
        test_automation.AutomationTests.client.close()
        cls.server = create_server("127.0.0.1", 0, test_automation.AutomationTests.server_pid)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.client = DisplayHDRRemoteClient(f"http://127.0.0.1:{cls.server.server_port}")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)
        test_automation.AutomationTests.tearDownClass()

    def state(self, **fields):
        response = self.client.request("set_state" if fields else "get_state", **fields)
        self.assertTrue(response["ok"], response)
        return response["state"]

    def key(self, name):
        response = self.client.request("key", key=name)
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["state"]["lastSetRequestId"], response["id"])
        self.assertTrue(response["state"]["presentation"]["applied"])
        return response["state"]

    def test_jump_keys(self):
        ids = ("ConnectionProperties", "TenPercentPeak", "FlashTest", "LongDurationWhite", "DualCornerBox",
               "StaticContrastRatio", "ColorPatches", "BitDepthPrecision", "RiseFallTime", "ProfileCurve")
        shifted = ("LocalDimmingContrast", "BlackLevelHDRvsSDR", "BlackLevelCrush", "SubTitleFlicker", "XRiteColors")
        for index, expected in enumerate(ids):
            self.assertEqual(self.key(str(index))["test"]["id"], expected)
        for index, expected in enumerate(shifted, 1):
            self.assertEqual(self.key(f"Shift+{index}")["test"]["id"], expected)

    def test_arrows_and_shift_step(self):
        self.state(test="ActiveDimming", settings={"activeDimmingPq": 450})
        self.assertEqual(self.key("Up")["settings"]["activeDimmingPq"], 451)
        self.assertEqual(self.key("Shift+Down")["settings"]["activeDimmingPq"], 441)
        self.assertEqual(self.key("Up")["settings"]["activeDimmingPq"], 442)
        self.state(test="ColorPatchesFull", settings={"color": "Red"})
        self.assertEqual(self.key("Down")["settings"]["color"], "Green")
        self.assertEqual(self.key("Down")["settings"]["color"], "Blue")
        self.assertEqual(self.key("Up")["settings"]["color"], "Green")
        self.assertEqual(self.key("Right")["test"]["id"], "BitDepthPrecision")
        self.assertEqual(self.key("Left")["test"]["id"], "ColorPatchesFull")

    def test_functions_and_other_keys(self):
        self.state(test="SubTitleFlicker", settings={"textVisible": True, "subtitlesVisible": True, "paused": False})
        self.assertFalse(self.key("Space")["settings"]["textVisible"])
        self.assertFalse(self.key("Control")["settings"]["subtitlesVisible"])
        self.assertEqual(self.key("C")["test"]["id"], "Cooldown")
        self.assertEqual(self.key("Home")["test"]["id"], "StartOfTest")
        for name in ("PageUp", "PageDown", "Pause", "A", "Comma", "Period", "Minus", "Plus",
                     "LeftBracket", "RightBracket", "Escape", "AltEnter", "AltEnter"):
            self.key(name)
        self.state(test="XRiteColors", settings={"xriteAuto": False, "xriteInterval": 5})
        self.assertTrue(self.key("A")["settings"]["xriteAuto"])
        self.assertAlmostEqual(self.key("Plus")["settings"]["xriteInterval"], 5.1, places=5)
        self.assertAlmostEqual(self.key("Minus")["settings"]["xriteInterval"], 5, places=5)

    def test_invalid_keys_are_atomic(self):
        before = self.state(test="ColorPatchesFull", settings={"color": "Blue"})
        for fields in ({}, {"key": "Bad"}, {"key": 1}, {"key": "Shift+Bad"}, {"key": "Up", "settings": {}}):
            self.assertFalse(self.client.request("key", **fields)["ok"])
        after = self.state()
        self.assertEqual(before["test"], after["test"])
        self.assertEqual(before["settings"], after["settings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
