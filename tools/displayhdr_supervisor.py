"""Own and restart the renderer while the HTTP service stays running."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import threading

from displayhdr_api import DisplayHDRClient


def launch(exe):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1
    return subprocess.Popen([str(exe), "--api"], cwd=exe.parent, startupinfo=startup)


def probe(pid):
    with DisplayHDRClient(pid, timeout=15) as client:
        result = client.request("catalog")
        if not result.get("ok"):
            raise RuntimeError(str(result))


def stop(process):
    if process.poll() is not None:
        return
    user = ctypes.WinDLL("user32")
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def close_window(window, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == process.pid:
            user.PostMessageW(window, 0x10, 0, 0)
        return True

    user.EnumWindows(close_window, 0)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)


class AttachedProcess:
    def __init__(self, pid):
        self.handle = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def poll(self):
        waited = self.kernel.WaitForSingleObject(self.handle, 0)
        if waited == 258:
            return None
        if waited != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()


class Supervisor:
    def __init__(self, exe, pid=None, launcher=launch, checker=probe, closer=stop):
        self.exe = Path(exe).resolve()
        self.attached_pid = pid
        self.process = None
        self.attached_process = None
        self.launcher, self.checker, self.closer = launcher, checker, closer
        self.lock = threading.Lock()
        self.phase = "starting"
        self.error = ""

    def status(self):
        with self.lock:
            process = self.process or self.attached_process
            if self.phase == "ready" and process is not None:
                code = process.poll()
                if code is not None:
                    self.phase = "stopped" if code == 0 else "failed"
                    self.error = "" if code == 0 else f"DisplayHDR exited with code {code}."
            return {"status": self.phase,
                    "pid": self.process.pid if self.process else self.attached_pid,
                    "restartSupported": self.attached_pid is None, "error": self.error}

    def start(self):
        try:
            if self.attached_pid is None:
                process = self.launcher(self.exe)
                with self.lock:
                    self.process = process
                pid = process.pid
            else:
                pid = self.attached_pid
                self.attached_process = AttachedProcess(pid)
            self.checker(pid)
            with self.lock:
                process = self.process or self.attached_process
                if process is not None and process.poll() is not None:
                    raise RuntimeError("DisplayHDR exited during startup.")
                self.phase, self.error = "ready", ""
        except Exception as error:
            # A partially started renderer must not survive a failed startup.
            try:
                if self.process is not None:
                    self.closer(self.process)
                if self.attached_process is not None:
                    self.attached_process.close()
                    self.attached_process = None
            except Exception as close_error:
                error = RuntimeError(f"{error}; cleanup failed: {close_error}")
            with self.lock:
                self.phase, self.error = "failed", str(error)

    def restart(self):
        with self.lock:
            if self.attached_pid is not None:
                raise ValueError("Restart is unavailable for an attached PID. Use a managed Host launcher.")
            if self.phase in ("starting", "restarting"):
                raise ValueError("Host is already starting or restarting.")
            self.phase, self.error = "restarting", ""
        threading.Thread(target=self._restart, daemon=True).start()

    def _restart(self):
        try:
            if self.process is not None:
                self.closer(self.process)
            with self.lock:
                self.phase = "starting"
            self.start()
        except Exception as error:
            with self.lock:
                self.phase, self.error = "failed", str(error)
