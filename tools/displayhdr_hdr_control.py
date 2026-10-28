"""Enable HDR on one verified active endpoint; never switches ports or disables HDR.

Packet layouts and enum values follow Microsoft's wingdi.h. Legacy advanced-color
state is not proof of HDR; the caller must also verify Host display.hdr.
"""
import ctypes as C
import os
import time

from displayhdr_display_paths import Header, I32, U32, WindowsApi, QDC_ONLY_ACTIVE_PATHS, key


class AdvancedColorInfo(C.Structure):
    _fields_ = [('header', Header), ('flags', U32), ('colorEncoding', U32),
                ('bitsPerColorChannel', U32)]


class AdvancedColorInfo2(C.Structure):
    _fields_ = AdvancedColorInfo._fields_ + [('activeColorMode', U32)]


class ColorState(C.Structure):
    _fields_ = [('header', Header), ('value', U32)]


class WindowsColorApi:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows is required')
        if (C.sizeof(AdvancedColorInfo), C.sizeof(AdvancedColorInfo2), C.sizeof(ColorState)) != (32, 36, 24):
            raise RuntimeError('Unexpected advanced-color structure layout')
        self.dll = C.WinDLL('user32')
        for name in ('DisplayConfigGetDeviceInfo', 'DisplayConfigSetDeviceInfo'):
            function = getattr(self.dll, name)
            function.argtypes, function.restype = [C.POINTER(Header)], I32

    def get(self, path):
        packet = AdvancedColorInfo2()
        packet.header = Header(15, C.sizeof(packet), path.target.adapter, path.target.id)
        code = self.dll.DisplayConfigGetDeviceInfo(C.byref(packet.header))
        legacy = code in (50, 87)
        if legacy:
            packet = AdvancedColorInfo()
            packet.header = Header(9, C.sizeof(packet), path.target.adapter, path.target.id)
            code = self.dll.DisplayConfigGetDeviceInfo(C.byref(packet.header))
        WindowsApi.check(code)
        flags = packet.flags
        return {'supported': bool(flags & (1 if legacy else 16)),
                'enabled': bool(flags & 2) if legacy else packet.activeColorMode == 2,
                'userEnabled': bool(flags & (2 if legacy else 32)),
                'limitedByPolicy': bool(flags & 8),
                'legacyAdvancedColor': legacy,
                'hdrActive': None if legacy else packet.activeColorMode == 2,
                'colorEncoding': packet.colorEncoding,
                'bitsPerColorChannel': packet.bitsPerColorChannel}

    def enable(self, path, state):
        packet = ColorState()
        packet.header = Header(10 if state['legacyAdvancedColor'] else 16,
                               C.sizeof(packet), path.target.adapter, path.target.id)
        packet.value = 1
        WindowsApi.check(self.dll.DisplayConfigSetDeviceInfo(C.byref(packet.header)))


class HdrControl:
    def __init__(self, display_api=None, color_api=None, sleep=time.sleep):
        self.display = display_api if display_api is not None else WindowsApi()
        self.color = color_api if color_api is not None else WindowsColorApi()
        self.sleep = sleep

    def _path(self, target_key, monitor_device_path):
        if not isinstance(target_key, str) or not target_key or not isinstance(monitor_device_path, str) or not monitor_device_path:
            raise ValueError('An endpoint key and monitor device path are required')
        paths = self.display.query(QDC_ONLY_ACTIVE_PATHS).paths
        if (len(paths) != 1 or not paths[0].flags & 1 or not paths[0].target.available
                or key(paths[0].target) != target_key
                or self.display.device_path(paths[0]) != monitor_device_path):
            raise ValueError('HDR control requires exactly the requested active display endpoint')
        return paths[0]

    def state(self, target_key, monitor_device_path):
        result = self.color.get(self._path(target_key, monitor_device_path))
        self._path(target_key, monitor_device_path)
        return {'targetKey': target_key, 'monitorDevicePath': monitor_device_path, **result}

    def enable(self, target_key, monitor_device_path):
        before = self.state(target_key, monitor_device_path)
        if not before['supported'] or before['limitedByPolicy']:
            raise ValueError('HDR is unsupported or advanced color is restricted by policy')
        if before['enabled']:
            return {'before': before, 'after': before, 'changed': False,
                    'requiresHostHdrVerification': True}
        self.color.enable(self._path(target_key, monitor_device_path), before)
        deadline = time.monotonic() + 5
        for attempt in range(26):
            after = self.state(target_key, monitor_device_path)
            if after['enabled']:
                return {'before': before, 'after': after, 'changed': True,
                        'requiresHostHdrVerification': True}
            remaining = deadline - time.monotonic()
            if attempt == 25 or remaining <= 0:
                break
            self.sleep(min(.2, remaining))
        raise RuntimeError('HDR enable was sent once, but active state was not confirmed within five seconds')
