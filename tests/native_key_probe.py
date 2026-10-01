"""Compare remote operations with actual Main.cpp keyboard handlers in one live process."""
import ctypes
from ctypes import wintypes
import json
import sys

from displayhdr_remote import DisplayHDRRemoteClient

client = DisplayHDRRemoteClient(f"http://127.0.0.1:{sys.argv[1]}")
renderer_pid = int(sys.argv[2])
user = ctypes.WinDLL("user32")
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user.SendMessageW.restype = wintypes.LPARAM
windows = []
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@callback_type
def find_window(window, _):
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(window, ctypes.byref(pid))
    name = ctypes.create_unicode_buffer(256)
    user.GetClassNameW(window, name, len(name))
    if pid.value == renderer_pid and name.value == "DisplayHDRComplianceTestsWindowClass":
        windows.append(window)
    return True


user.EnumWindows(find_window, 0)
assert len(windows) == 1, windows
window = windows[0]
virtual = {"Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27, "Space": 0x20,
           "Control": 0x11, "Home": 0x24, "P": 0x50, "A": 0x41, "C": 0x43,
           "Period": 0xBE, "Comma": 0xBC, "Plus": 0xBB, "Minus": 0xBD,
           "LeftBracket": 0xDB, "RightBracket": 0xDD, "Escape": 0x1B,
           "Pause": 0x13, "PageUp": 0x21, "PageDown": 0x22}
defaults = {"textVisible": True, "subtitlesVisible": True, "paused": False, "fullscreen": False,
            "color": "Red", "testingTier": 400, "checkerboard": "6x4", "whiteLevel": 100,
            "blackIndex": 0, "profileIndex": 0, "xriteIndex": 0, "xriteAuto": False,
            "xriteInterval": 5, "dimmingMode": "1D", "gradient": {"r": 1, "g": 1, "b": 1},
            "staticContrastPq": 450, "staticContrastSrgb": 100, "activeDimmingPq": 450,
            "activeDimmingDarkPq": 250, "calibrationMaxPq": 500, "calibrationFullFramePq": 500,
            "calibrationMinPq": 10, "calibrationMaxSrgb": 100, "calibrationFullFrameSrgb": 100,
            "calibrationMinSrgb": 10}
cases = [("ColorPatchesFull", key) for key in ("Up", "Down", "Left", "Right", "PageUp", "PageDown",
         "Space", "Control", "C", "Home", "P", "Pause", "Period", "Comma", "LeftBracket",
         "RightBracket", "Escape", "AltEnter")]
cases += [("ColorPatchesFull", str(i)) for i in range(10)]
cases += [("ColorPatchesFull", f"Shift+{i}") for i in range(1, 10)]
for test in ("ActiveDimming", "ActiveDimmingDark", "StaticContrastRatio", "BlackLevelCrush",
             "TenPercentPeak", "ProfileCurve", "XRiteColors", "LocalDimmingContrast"):
    cases += [(test, key) for key in ("Up", "Down", "Shift+Up", "Shift+Down")]
cases += [("XRiteColors", key) for key in ("A", "Plus", "Minus", "Shift+Plus", "Shift+Minus")]
results = []
for test, key in cases:
    reset = client.request("set_state", test=test, settings=defaults, restart=True)
    assert reset["ok"], reset
    name = key.removeprefix("Shift+")
    shift = key.startswith("Shift+")
    if shift:
        user.SendMessageW(window, 0x100, 0x10, 0)
    if name == "AltEnter":
        user.SendMessageW(window, 0x104, 0x0D, 0x20000000)
    else:
        vk = ord(name) if len(name) == 1 and name.isdigit() else virtual[name]
        user.SendMessageW(window, 0x100 if name in ("Up", "Down") else 0x101, vk, 0)
    if shift:
        user.SendMessageW(window, 0x101, 0x10, 0)
    local = client.request()["state"]
    reset = client.request("set_state", test=test, settings=defaults, restart=True)
    assert reset["ok"], reset
    response = client.request("key", key=key)
    assert response["ok"], response
    remote = response["state"]
    assert local["test"]["id"] == remote["test"]["id"], (test, key, local["test"], remote["test"])
    assert local["settings"] == remote["settings"], (test, key, local["settings"], remote["settings"])
    results.append({"test": test, "key": key, "matched": True})
print(json.dumps({"ok": True, "comparisons": len(results), "results": results}))
