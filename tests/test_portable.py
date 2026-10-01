"""Verify ZIP contents and bundled runtimes without system Python discovery."""
import hashlib
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from zipfile import ZipFile


class PortableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workspace = Path(__file__).resolve().parents[2]
        cls.boundary = (workspace / "build-output").resolve()
        cls.stage = Path(tempfile.mkdtemp(prefix="portable 中文 空白-", dir=cls.boundary))
        assert cls.stage.resolve().is_relative_to(cls.boundary)
        cls.roots = []
        for role in ("Host", "Client"):
            with ZipFile(workspace / f"packages/DisplayHDR_{role}_x64.zip") as archive:
                assert archive.testzip() is None
                archive.extractall(cls.stage)
            cls.roots.append(cls.stage / f"DisplayHDR_{role}_x64")
        cls.environment = os.environ.copy()
        cls.environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        cls.environment["PYTHONHOME"] = "C:/nonexistent-python-home"
        cls.environment["PYTHONPATH"] = "C:/nonexistent-python-path"

    @classmethod
    def tearDownClass(cls):
        assert cls.stage.resolve().is_relative_to(cls.boundary)
        shutil.rmtree(cls.stage)

    def test_manifests_match_complete_extracted_content(self):
        for root in self.roots:
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(manifest["pythonVersion"], "3.13.16")
            for relative, expected in manifest["files"].items():
                self.assertEqual(hashlib.sha256((root / relative).read_bytes()).hexdigest(), expected, relative)
            if manifest["role"] == "Host":
                self.assertTrue((root / "DisplayHDRComplianceTests.exe").is_file())
            else:
                self.assertFalse((root / "DisplayHDRComplianceTests.exe").exists())

    def test_isolated_python_and_runtime_dlls_are_bundled(self):
        code = '''import ctypes,json,sys
from pathlib import Path
import http.server,urllib.request
kernel=ctypes.WinDLL("kernel32")
kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
paths={}
for name in ("python313.dll","vcruntime140.dll","vcruntime140_1.dll","libffi-8.dll"):
    dll=ctypes.WinDLL(name)
    buffer=ctypes.create_unicode_buffer(4096)
    assert kernel.GetModuleFileNameW(dll._handle,buffer,len(buffer))
    paths[name]=buffer.value
print(json.dumps({"isolated":sys.flags.isolated,"executable":sys.executable,"path":sys.path,"dlls":paths}))
'''
        for root in self.roots:
            runtime = root / "runtime/python.exe"
            run = subprocess.run([str(runtime), "-X", "utf8", "-c", code], cwd=root,
                                 env=self.environment, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
            result = json.loads(run.stdout)
            self.assertEqual(result["isolated"], 1)
            self.assertEqual(Path(result["executable"]), runtime)
            for path in result["path"]:
                self.assertTrue(Path(path).is_relative_to(root))
            for path in result["dlls"].values():
                self.assertEqual(Path(path).parent, runtime.parent)

    def test_launchers_work_with_no_python_on_path(self):
        for root, launcher in zip(self.roots, ("StartDisplayHDR.cmd", "ControlDisplayHDR.cmd")):
            run = subprocess.run([os.environ["ComSpec"], "/d", "/c", str(root / launcher), "--help"],
                                 cwd=root, env=self.environment, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
            self.assertIn(b"usage:", run.stdout)

    def test_client_gui_uses_bundled_qt(self):
        root = self.roots[1]
        code = '''import ctypes,json,sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from displayhdr_gui import RemoteWindow
app=QApplication([])
window=RemoteWindow()
window.show()
app.processEvents()
kernel=ctypes.WinDLL("kernel32")
kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype=ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
paths={}
for name in ("Qt6Core.dll","Qt6Gui.dll","Qt6Widgets.dll","pyside6.abi3.dll","shiboken6.abi3.dll","msvcp140.dll"):
    handle=kernel.GetModuleHandleW(name)
    assert handle,name
    buffer=ctypes.create_unicode_buffer(4096)
    assert kernel.GetModuleFileNameW(handle,buffer,len(buffer))
    paths[name]=buffer.value
print(json.dumps({"dlls":paths,"buttons":len(window.buttons),"platform":app.platformName()}))
window.close()
'''
        environment = {**self.environment, "QT_QPA_PLATFORM": "offscreen", "QT_PLUGIN_PATH": "C:/nonexistent-qt"}
        run = subprocess.run([str(root / "runtime/python.exe"), "-X", "utf8", "-c", code], cwd=root,
                             env=environment, capture_output=True, timeout=25)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        result = json.loads(run.stdout)
        self.assertEqual(result["buttons"], 33)
        self.assertEqual(result["platform"], "offscreen")
        for path in result["dlls"].values():
            self.assertTrue(Path(path).is_relative_to(root / "runtime"), path)
        self.assertTrue((root / "StartDisplayHDRClient.cmd").is_file())

    def test_gui_launcher_opens_and_closes_from_unc_path(self):
        root = self.roots[1]
        environment = {**self.environment, "QT_QPA_PLATFORM": "windows", "QT_PLUGIN_PATH": "C:/nonexistent-qt"}
        run = subprocess.run([os.environ["ComSpec"], "/d", "/c", str(root / "StartDisplayHDRClient.cmd")],
                             cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(run.returncode, 0)
        user = ctypes.WinDLL("user32")
        kernel = ctypes.WinDLL("kernel32")
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def locate(window, _):
            title = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(window, title, len(title))
            if title.value != "DisplayHDR 遙控器":
                return True
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid.value)
            if handle:
                path = ctypes.create_unicode_buffer(4096)
                size = wintypes.DWORD(len(path))
                if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)) and Path(path.value) == root / "runtime/pythonw.exe":
                    found.append((window, handle))
                else:
                    kernel.CloseHandle(handle)
            return True

        end = time.monotonic() + 10
        while not found and time.monotonic() < end:
            user.EnumWindows(locate, 0)
            time.sleep(.05)
        self.assertEqual(len(found), 1, "Packaged GUI launcher did not create its window.")
        window, handle = found[0]
        try:
            user.PostMessageW(window, 0x10, 0, 0)
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
        finally:
            kernel.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
