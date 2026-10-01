"""Windows Named Pipe client for the DisplayHDR automation API (standard library only)."""
import argparse
import ctypes
from ctypes import wintypes
import json
import time
import uuid


class Overlapped(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateEventW.restype = wintypes.HANDLE
kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
for function in (kernel.ReadFile, kernel.WriteFile):
    function.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(Overlapped)]
kernel.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped),
                                     ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped)]


class DisplayHDRClient:
    def __init__(self, pid, timeout=5):
        self.timeout = timeout
        name = rf"\\.\pipe\DisplayHDRTest-v1.2-{pid}"
        deadline = time.monotonic() + timeout
        self.handle = None
        while time.monotonic() < deadline:
            handle = kernel.CreateFileW(name, 0xC0000000, 0, None, 3, 0x40000000, None)
            if handle != ctypes.c_void_p(-1).value:
                self.handle = handle
                break
            error = ctypes.get_last_error()
            if error not in (2, 231):
                raise ctypes.WinError(error)
            kernel.WaitNamedPipeW(name, 50)
            time.sleep(0.01)
        if self.handle is None:
            raise TimeoutError("DisplayHDR pipe not available. Launch the program with --api.")
        self._buffer = b""

    def close(self):
        if self.handle is not None:
            kernel.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _transfer(self, data, reading, deadline):
        buffer = ctypes.create_string_buffer(4096 if reading else data)
        operation = Overlapped()
        operation.hEvent = kernel.CreateEventW(None, True, False, None)
        if not operation.hEvent:
            raise ctypes.WinError(ctypes.get_last_error())
        count = wintypes.DWORD()
        try:
            function = kernel.ReadFile if reading else kernel.WriteFile
            length = 4096 if reading else len(data)
            done = function(self.handle, buffer, length, ctypes.byref(count), ctypes.byref(operation))
            if not done:
                error = ctypes.get_last_error()
                if error != 997:
                    raise ctypes.WinError(error)
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if kernel.WaitForSingleObject(operation.hEvent, remaining) != 0:
                    kernel.CancelIoEx(self.handle, ctypes.byref(operation))
                    kernel.GetOverlappedResult(self.handle, ctypes.byref(operation), ctypes.byref(count), True)
                    raise TimeoutError("Request timed out; reconnect and query lastSetRequestId before retrying.")
                if not kernel.GetOverlappedResult(self.handle, ctypes.byref(operation), ctypes.byref(count), False):
                    raise ctypes.WinError(ctypes.get_last_error())
            if not count.value:
                raise ConnectionError("DisplayHDR disconnected.")
            return buffer.raw[:count.value] if reading else count.value
        finally:
            kernel.CloseHandle(operation.hEvent)

    def request(self, command="get_state", **fields):
        request = {"version": 1, "id": fields.pop("id", str(uuid.uuid4())), "command": command, **fields}
        return self.send(request)

    def send(self, request):
        encoded = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
        if len(encoded) > 16384:
            raise ValueError("Request exceeds the 16 KiB limit.")
        deadline = time.monotonic() + self.timeout
        sent = 0
        while sent < len(encoded):
            sent += self._transfer(encoded[sent:], False, deadline)
        while b"\n" not in self._buffer:
            self._buffer += self._transfer(None, True, deadline)
            if len(self._buffer) > 65536:
                raise ValueError("Response exceeds the client limit.")
        line, self._buffer = self._buffer.split(b"\n", 1)
        response = json.loads(line)
        if response.get("id") != request.get("id", ""):
            raise ValueError("Response id does not match the request.")
        return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--command", choices=["catalog", "get_state", "set_state", "key"], default="get_state")
    parser.add_argument("--key")
    parser.add_argument("--test")
    parser.add_argument("--settings", type=json.loads)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    fields = {}
    if args.key is not None:
        fields["key"] = args.key
    if args.test is not None:
        fields["test"] = args.test
    if args.settings is not None:
        fields["settings"] = args.settings
    if args.restart:
        fields["restart"] = True
    with DisplayHDRClient(args.pid) as client:
        result = client.request(args.command, **fields)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
