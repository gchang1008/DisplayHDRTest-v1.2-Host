"""Launch both extracted packages with no system Python on PATH and run GUI acceptance."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

repo = Path(__file__).resolve().parents[1]
workspace = repo.parent
stage = Path(tempfile.mkdtemp(prefix="GUI 實機驗收-", dir=workspace / "build-output/portable-verification"))
for role in ("Host", "Client"):
    with ZipFile(workspace / f"packages/DisplayHDR_{role}_x64.zip") as archive:
        archive.extractall(stage)
host = stage / "DisplayHDR_Host_x64"
client = stage / "DisplayHDR_Client_x64"
environment = os.environ.copy()
environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
environment["PYTHONHOME"] = "C:/nonexistent-python"
environment["PYTHONPATH"] = "C:/nonexistent-python"
environment["QT_PLUGIN_PATH"] = "C:/nonexistent-qt"
environment["QT_QPA_PLATFORM"] = "windows"
with socket.socket() as free:
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
log_path = workspace / "build-output/gui-live-host.log"
with log_path.open("w", encoding="utf-8") as log:
    service = subprocess.Popen([str(host / "runtime/python.exe"), "-X", "utf8", "displayhdr_server.py",
                                "--host", "127.0.0.1", "--port", str(port)], cwd=host,
                               env=environment, stdout=log, stderr=log)
    renderer_pid = None
    try:
        end = time.monotonic() + 20
        while time.monotonic() < end:
            text = log_path.read_text(encoding="utf-8")
            if "READY" in text:
                import re
                renderer_pid = int(re.search(r"pid[= :]+(\d+)", text).group(1))
                break
            if service.poll() is not None:
                raise RuntimeError(text)
            time.sleep(.1)
        assert renderer_pid, log_path.read_text(encoding="utf-8")
        result = subprocess.run([str(client / "runtime/python.exe"), "-X", "utf8",
                                 str(repo / "tests/gui_live_probe.py"), str(port),
                                 str(workspace / "build-output/displayhdr-gui-preview.png")],
                                cwd=client, env=environment, capture_output=True, timeout=40)
        (workspace / "build-output/gui-live-client.log").write_bytes(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        report = json.loads(result.stdout)
        native = subprocess.run([str(client / "runtime/python.exe"), "-X", "utf8",
                                 str(repo / "tests/native_key_probe.py"), str(port), str(renderer_pid)],
                                cwd=client, env=environment, capture_output=True, timeout=60)
        (workspace / "build-output/gui-native-key.log").write_bytes(native.stdout + native.stderr)
        assert native.returncode == 0, native.stderr.decode("utf-8", errors="replace")
        report["nativeKeyComparison"] = json.loads(native.stdout)
        report["stage"] = str(stage)
        report["rendererPid"] = renderer_pid
        (workspace / "build-output/gui-live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": report["ok"], "platform": report["platform"], "tests": report["tests"], "stage": str(stage)}, ensure_ascii=False))
    finally:
        if renderer_pid:
            user = ctypes.WinDLL("user32")
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            @callback_type
            def close_window(window, _):
                pid = wintypes.DWORD()
                user.GetWindowThreadProcessId(window, ctypes.byref(pid))
                if pid.value == renderer_pid:
                    user.PostMessageW(window, 0x10, 0, 0)
                return True

            user.EnumWindows(close_window, 0)
        try:
            service.wait(timeout=10)
        except subprocess.TimeoutExpired:
            service.terminate()
            service.wait(timeout=5)
            raise AssertionError("Host service did not shut down cleanly.")
