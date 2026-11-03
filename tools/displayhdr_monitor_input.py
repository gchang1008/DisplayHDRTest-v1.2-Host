"""Bounded native VCP 0x60 reads and explicitly requested input writes."""
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


class InputIdentityError(ValueError):
    pass


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
            (self.dxva.SetVCPFeature, [C.c_void_p, C.c_ubyte, U32]),
            (self.dxva.GetVCPFeatureAndVCPFeatureReply,
             [C.c_void_p, C.c_ubyte, C.POINTER(I32), C.POINTER(U32), C.POINTER(U32)]))
        for function, arguments in functions:
            function.argtypes, function.restype = arguments, I32

    @staticmethod
    def check(success):
        if not success:
            raise C.WinError(C.get_last_error())

    def read(self, device):
        return self.transfer(device)

    def write(self, device, value):
        return self.transfer(device, value)

    def transfer(self, device, value=None):
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
            raise InputIdentityError('The active GDI display must identify exactly one logical monitor.')
        count = U32()
        self.check(self.dxva.GetNumberOfPhysicalMonitorsFromHMONITOR(matches[0], C.byref(count)))
        if count.value != 1:
            raise InputIdentityError('The active GDI display must identify exactly one physical monitor.')
        physical = (PhysicalMonitor * 1)()
        self.check(self.dxva.GetPhysicalMonitorsFromHMONITOR(matches[0], 1, physical))
        result = {}
        try:
            if value is not None:
                self.check(self.dxva.SetVCPFeature(physical[0].handle, 0x60, value))
                return {"accepted": True, "vcpCode": "60", "value": value}
            kind, current, maximum = I32(), U32(), U32()
            self.check(self.dxva.GetVCPFeatureAndVCPFeatureReply(
                physical[0].handle, 0x60, C.byref(kind), C.byref(current), C.byref(maximum)))
            result.update(ok=True, vcpCode='60', currentRaw=current.value, maximumRaw=maximum.value,
                          codeType=kind.value, physicalDescription=physical[0].description,
                          **decode_input(current.value))
        finally:
            self.check(self.dxva.DestroyPhysicalMonitors(1, physical))
        return result


def query_input(display=None, ddc=None, write=None, read=None):
    started = time.monotonic()
    display = display or WindowsApi()
    paths = display.query(QDC_ONLY_ACTIVE_PATHS).paths
    if read is not None and write is not None:
        raise ValueError('Read and write cannot be combined.')
    selected = [p for p in paths if key(p.target) == read[0] and display.device_path(p) == read[1]] if read else paths
    if len(selected) != 1 or not selected[0].flags & 1 or not selected[0].target.available or read is None and len(paths) != 1:
        raise InputIdentityError('Native input query requires exactly one active available endpoint.')
    path = selected[0]
    if sum(key(p.source) == key(path.source) for p in paths) != 1:
        raise InputIdentityError('Mirrored output cannot identify a unique DDC/CI path.')
    topology = sorted((key(p.target), display.device_path(p), key(p.source)) for p in paths)
    device_path = display.device_path(path)
    if not device_path:
        raise InputIdentityError('Active monitor identity is unavailable.')
    name = SourceName()
    name.header = Header(1, C.sizeof(name), path.source.adapter, path.source.id)
    WindowsApi.check(display.dll.DisplayConfigGetDeviceInfo(C.byref(name.header)))
    if write is not None:
        target, identity, value = write
        if key(path.target) != target or device_path != identity:
            raise InputIdentityError("Active display identity changed before DDC write.")
        if type(value) is not int or not 1 <= value <= 255:
            raise ValueError("Invalid DDC input value.")
        result = (ddc or WindowsDdc()).write(name.device, value)
    else:
        result = (ddc or WindowsDdc()).read(name.device)
    after = display.query(QDC_ONLY_ACTIVE_PATHS).paths
    if (sorted((key(p.target), display.device_path(p), key(p.source)) for p in after) != topology
            or not all(p.flags & 1 and p.target.available for p in after)):
        raise InputIdentityError('Active monitor identity changed during the native query.')
    return {**result, 'targetKey': key(path.target), 'monitorDevicePath': device_path,
            'gdiDevice': name.device, 'durationSeconds': time.monotonic() - started}


def probe_native(target=None, identity=None):
    arguments = ['--worker'] if target is None else ['--read', target, identity]
    result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), *arguments],
                            capture_output=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or len(result.stdout) > 65536:
        raise RuntimeError('Native DDC/CI worker failed or exceeded the output bound.')
    return json.loads(result.stdout.decode('utf-8'))


def read_native(target, identity):
    result = probe_native(target, identity)
    if result.get('ok') is not True:
        error = InputIdentityError if result.get('identityMismatch') else RuntimeError
        raise error(result.get('error', 'Native DDC/CI path query failed.'))
    return result


def native_value():
    result = probe_native()
    if result.get('ok') is not True:
        raise OSError(result.get('errorCode', 0), result.get('error', 'Native DDC/CI query failed.'))
    return result['currentRaw']


def write_native(target, identity, value):
    result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
        '--write', target, identity, str(value)], capture_output=True, timeout=3,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or len(result.stdout) > 65536:
        raise RuntimeError('DDC writer failed; outcome may be unknown. No retry was sent.')
    report = json.loads(result.stdout.decode('utf-8'))
    if report.get('accepted') is not True:
        raise RuntimeError(report.get('error', 'DDC input write failed.'))
    return report


if __name__ == '__main__':
    writing = len(sys.argv) == 5 and sys.argv[1] == '--write'
    reading = len(sys.argv) == 4 and sys.argv[1] == '--read'
    if sys.argv[1:] != ['--worker'] and not writing and not reading:
        raise SystemExit('Only fixed native worker entry points are supported.')
    try:
        reply = query_input(write=(sys.argv[2], sys.argv[3], int(sys.argv[4])) if writing else None,
                            read=(sys.argv[2], sys.argv[3]) if reading else None)
    except (OSError, ValueError, RuntimeError) as error:
        reply = {'ok': False, 'errorCode': getattr(error, 'winerror', None) or getattr(error, 'errno', 0),
                 'error': str(error), 'identityMismatch': isinstance(error, InputIdentityError)}
    print(json.dumps(reply, ensure_ascii=True))
