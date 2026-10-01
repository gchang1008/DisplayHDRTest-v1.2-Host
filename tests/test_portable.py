"""Verify ZIP contents and bundled runtimes without system Python discovery."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
