"""Read VCP 0x60 through Windows DXVA2; never writes monitor settings."""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from displayhdr_display_paths import Header, I32, U32, WindowsApi, QDC_ONLY_ACTIVE_PATHS, key


class Rect(C.Structure):
    _fields_ = [(name, I32) for name in ('left', 'top', 'right', 'bottom')]


class MonitorInfo(C.Structure):
    _fields_ = [('size', U32), ('monitor', Rect), ('work', Rect), ('flags', U32),
                ('device', C.c_wchar * 32)]


class PhysicalMonitor(C.Structure):
    _fields_ = [('handle', C.c_void_p), ('description', C.c_wchar * 128)]


class SourceName(C.Structure):
    _fields_ = [('header', Header), ('device', C.c_wchar * 32)]


def decode_input(raw):
    if 0 <= raw <= 255:
        return {'currentValue': raw, 'valueFormat': 'singleByte'}
    if raw <= 65535 and raw >> 8 == raw & 255:
        return {'currentValue': raw & 255, 'valueFormat': 'duplicatedByte'}
    return {'currentValue': None, 'valueFormat': 'unrecognized'}


class WindowsDdc:
    def __init__(self, user=None, dxva=None):
        if os.name != 'nt':
            raise OSError('Windows is required.')
        if C.sizeof(SourceName) != 84 or C.sizeof(MonitorInfo) != 104:
            raise RuntimeError('Unexpected monitor structure layout.')
        self.user = user or C.WinDLL('user32', use_last_error=True)
        self.dxva = dxva or C.WinDLL('dxva2', use_last_error=True)
        self.callback = C.WINFUNCTYPE(I32, C.c_void_p, C.c_void_p, C.POINTER(Rect), C.c_ssize_t)
        functions = (
            (self.user.EnumDisplayMonitors, [C.c_void_p, C.POINTER(Rect), self.callback, C.c_ssize_t]),
            (self.user.GetMonitorInfoW, [C.c_void_p, C.POINTER(MonitorInfo)]),
            (self.dxva.GetNumberOfPhysicalMonitorsFromHMONITOR, [C.c_void_p, C.POINTER(U32)]),
            (self.dxva.GetPhysicalMonitorsFromHMONITOR, [C.c_void_p, U32, C.POINTER(PhysicalMonitor)]),
            (self.dxva.DestroyPhysicalMonitors, [U32, C.POINTER(PhysicalMonitor)]),
            (self.dxva.GetVCPFeatureAndVCPFeatureReply,
             [C.c_void_p, C.c_ubyte, C.POINTER(I32), C.POINTER(U32), C.POINTER(U32)]))
        for function, arguments in functions:
            function.argtypes, function.restype = arguments, I32

    @staticmethod
    def check(success):
        if not success:
            raise C.WinError(C.get_last_error())

    def read(self, device):
        monitors = []
        callback = self.callback(lambda handle, dc, rect, data: monitors.append(handle) or 1)
        self.check(self.user.EnumDisplayMonitors(None, None, callback, 0))
        matches = []
        for handle in monitors:
            info = MonitorInfo()
            info.size = C.sizeof(info)
            self.check(self.user.GetMonitorInfoW(handle, C.byref(info)))
            if info.device.casefold() == device.casefold():
                matches.append(handle)
        if len(matches) != 1:
            raise ValueError('The active GDI display must identify exactly one logical monitor.')
        count = U32()
        self.check(self.dxva.GetNumberOfPhysicalMonitorsFromHMONITOR(matches[0], C.byref(count)))
        if count.value != 1:
            raise ValueError('The active GDI display must identify exactly one physical monitor.')
        physical = (PhysicalMonitor * 1)()
        self.check(self.dxva.GetPhysicalMonitorsFromHMONITOR(matches[0], 1, physical))
        result = {}
        try:
            kind, current, maximum = I32(), U32(), U32()
            self.check(self.dxva.GetVCPFeatureAndVCPFeatureReply(
                physical[0].handle, 0x60, C.byref(kind), C.byref(current), C.byref(maximum)))
            result.update(ok=True, vcpCode='60', currentRaw=current.value, maximumRaw=maximum.value,
                          codeType=kind.value, physicalDescription=physical[0].description,
                          **decode_input(current.value))
        finally:
            self.check(self.dxva.DestroyPhysicalMonitors(1, physical))
        return result


def query_input(display=None, ddc=None):
    started = time.monotonic()
    display = display or WindowsApi()
    paths = display.query(QDC_ONLY_ACTIVE_PATHS).paths
    if len(paths) != 1 or not paths[0].flags & 1 or not paths[0].target.available:
        raise ValueError('Native input query requires exactly one active available endpoint.')
    path = paths[0]
    device_path = display.device_path(path)
    if not device_path:
        raise ValueError('Active monitor identity is unavailable.')
    name = SourceName()
    name.header = Header(1, C.sizeof(name), path.source.adapter, path.source.id)
    WindowsApi.check(display.dll.DisplayConfigGetDeviceInfo(C.byref(name.header)))
    result = (ddc or WindowsDdc()).read(name.device)
    after = display.query(QDC_ONLY_ACTIVE_PATHS).paths
    if (len(after) != 1 or not after[0].flags & 1 or key(after[0].target) != key(path.target)
            or display.device_path(after[0]) != device_path):
        raise ValueError('Active monitor identity changed during the native query.')
    return {**result, 'targetKey': key(path.target), 'monitorDevicePath': device_path,
            'gdiDevice': name.device, 'durationSeconds': time.monotonic() - started}


def probe_native():
    result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker'],
                            capture_output=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or len(result.stdout) > 65536:
        raise RuntimeError('Native DDC/CI worker failed or exceeded the output bound.')
    return json.loads(result.stdout.decode('utf-8'))


def native_value():
    result = probe_native()
    if result.get('ok') is not True:
        raise OSError(result.get('errorCode', 0), result.get('error', 'Native DDC/CI query failed.'))
    return result['currentRaw']


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('Only the fixed read-only worker entry point is supported.')
    try:
        reply = query_input()
    except (OSError, ValueError, RuntimeError) as error:
        reply = {'ok': False, 'errorCode': getattr(error, 'winerror', None) or getattr(error, 'errno', 0),
                 'error': str(error)}
    print(json.dumps(reply, ensure_ascii=True))
