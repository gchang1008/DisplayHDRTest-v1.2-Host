"""Bounded, endpoint-verified Windows HDR and physical brightness operations."""
import base64
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from displayhdr_display_paths import Header, I32, U32, TargetName, WindowsApi, QDC_ONLY_ACTIVE_PATHS, key
from displayhdr_hdr_control import WindowsColorApi
from displayhdr_monitor_input import MonitorInfo, PhysicalMonitor, Rect, SourceName, InputIdentityError
from displayhdr_edid import monitor_instance
from displayhdr_factor import dxgi_output, guid, method, read_factor, release


COMMANDS = {"get_display_controls", "set_display_hdr", "set_display_brightness", "get_brightness_factor"}
INTERNAL = {6, 11, 13, 0x80000000}
FACTOR_TECHNOLOGIES = {11, 0x80000000}
MCCS_COMPATIBILITY_ERRORS = (0xc0262587, 0xc02625d9, 0xc02625da, 0xc02625db, 0xc02625dc)


def measure(trace, stage, call, *args):
    started = time.perf_counter()
    event = {'stage': stage, 'result': 'ok'}
    try:
        return call(*args)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        event.update(result='error', reason=str(error)[:1024])
        raise
    finally:
        event['elapsedMs'] = (time.perf_counter() - started) * 1000
        trace.append(event)


class ControlError(RuntimeError):
    def __init__(self, message, trace, elapsed):
        super().__init__(message)
        self.controlTrace, self.controlElapsedMs = trace, elapsed


def legacy_hdr_info(display, path):
    source = SourceName()
    source.header = Header(1, C.sizeof(source), path.source.adapter, path.source.id)
    WindowsApi.check(display.dll.DisplayConfigGetDeviceInfo(C.byref(source.header)))
    output = dxgi_output((path.source.adapter.high, path.source.adapter.low), source.device)
    if not output.monitor:
        raise ValueError('The active output did not identify a Windows monitor for HDR.')

    runtime = C.WinDLL('combase')
    pointer = C.c_void_p
    out_pointer = C.POINTER(pointer)
    for function, args in ((runtime.RoInitialize, [U32]),
                           (runtime.WindowsCreateString, [C.c_wchar_p, U32, out_pointer]),
                           (runtime.WindowsDeleteString, [pointer]),
                           (runtime.RoGetActivationFactory, [pointer, pointer, out_pointer])):
        function.argtypes, function.restype = args, I32
    runtime.RoUninitialize.argtypes, runtime.RoUninitialize.restype = [], None

    def check(result):
        if result < 0:
            raise OSError(f'Windows HDR capability query failed: 0x{result & 0xffffffff:08X}.')

    name = 'Windows.Graphics.Display.DisplayInformation'
    string, factory, monitor, info = pointer(), pointer(), pointer(), pointer()
    check(runtime.RoInitialize(1))
    try:
        check(runtime.WindowsCreateString(name, len(name), C.byref(string)))
        check(runtime.RoGetActivationFactory(string, guid('7449121c-382b-4705-8da7-a795ba482013'),
                                             C.byref(factory)))
        # GetForMonitor returns IDisplayInformation5, which exposes GetAdvancedColorInfo.
        check(method(factory, 7, [pointer, pointer, out_pointer], output.monitor,
                     guid('3a5442dc-2cde-4a8d-80d1-21dc5adcc1aa'), C.byref(monitor)))
        check(method(monitor, 6, [out_pointer], C.byref(info)))
        kind, available = I32(), C.c_ubyte()
        check(method(info, 6, [C.POINTER(I32)], C.byref(kind)))
        check(method(info, 16, [I32, C.POINTER(C.c_ubyte)], 2, C.byref(available)))
        if kind.value not in (0, 1, 2):
            raise ValueError('Windows reported an unknown advanced color mode.')
        return bool(available.value), kind.value
    finally:
        release(info)
        release(monitor)
        release(factory)
        if string:
            runtime.WindowsDeleteString(string)
        runtime.RoUninitialize()


WMI_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $rows = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness |
        Where-Object { $_.Active -and (($_.InstanceName -replace '_\d+$', '') -ieq $request.instance) })
    if ($rows.Count -ne 1) { throw 'A unique active Windows brightness device was not found.' }
    $levels = @($rows[0].Level | Sort-Object -Unique)
    if ($levels.Count -eq 0) { throw 'Windows did not report supported brightness levels.' }
    $methods = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods |
        Where-Object { $_.Active -and $_.InstanceName -ieq $rows[0].InstanceName })
    if ($methods.Count -ne 1) { throw 'A unique Windows brightness setter was not found.' }
    $changed = $false
    if ($null -ne $request.percent) {
        $desired = $levels | Sort-Object @{Expression={ [Math]::Abs([int]$_ - [int]$request.percent) }}, @{Expression={ [int]$_ }} | Select-Object -First 1
        if ([int]$rows[0].CurrentBrightness -ne [int]$desired) {
            $reply = Invoke-CimMethod -InputObject $methods[0] -MethodName WmiSetBrightness -Arguments @{Timeout=[uint32]0; Brightness=[byte]$desired}
            if ($null -ne $reply.ReturnValue -and $reply.ReturnValue -ne 0) { throw "Windows brightness write returned error $($reply.ReturnValue)." }
            $changed = $true
        }
        $rows = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness |
            Where-Object { $_.Active -and (($_.InstanceName -replace '_\d+$', '') -ieq $request.instance) })
        if ($rows.Count -ne 1 -or [int]$rows[0].CurrentBrightness -ne [int]$desired) { throw 'Windows brightness write was not confirmed; no retry was sent.' }
    }
    @{current=[int]$rows[0].CurrentBrightness; minimum=[int]$levels[0]; maximum=[int]$levels[-1]; levels=$levels; changed=$changed} | ConvertTo-Json -Compress
} catch {
    @{error=$_.Exception.Message} | ConvertTo-Json -Compress
}
'''


def windows_brightness(identity, percent=None):
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(WMI_SCRIPT.encode('utf-16-le')).decode('ascii')],
        input=json.dumps({'instance': monitor_instance(identity), 'percent': percent}).encode('utf-8'),
        capture_output=True, timeout=4, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or len(result.stdout) > 65536:
        raise RuntimeError('Windows brightness worker failed or exceeded the output limit.')
    reply = json.loads(result.stdout.decode('utf-8-sig'))
    if 'error' in reply:
        raise RuntimeError(reply['error'])
    current, minimum, maximum = (reply.get(k) for k in ('current', 'minimum', 'maximum'))
    levels = reply.get('levels')
    if (any(type(v) is not int or not 0 <= v <= 100 for v in (current, minimum, maximum))
            or not minimum <= current <= maximum or not isinstance(levels, list)
            or not levels or any(type(v) is not int or not 0 <= v <= 100 for v in levels)
            or current not in levels or minimum != min(levels) or maximum != max(levels)):
        raise ValueError('Windows returned malformed brightness levels.')
    return {**reply, 'percent': current}


class WindowsBrightness:
    def __init__(self, user=None, dxva=None, trace=None):
        self.trace = trace if trace is not None else []
        self.user = user or C.WinDLL('user32', use_last_error=True)
        self.dxva = dxva or C.WinDLL('dxva2', use_last_error=True)
        self.callback = C.WINFUNCTYPE(I32, C.c_void_p, C.c_void_p, C.POINTER(Rect), C.c_ssize_t)
        signatures = (
            (self.user.EnumDisplayMonitors, [C.c_void_p, C.POINTER(Rect), self.callback, C.c_ssize_t]),
            (self.user.GetMonitorInfoW, [C.c_void_p, C.POINTER(MonitorInfo)]),
            (self.dxva.GetNumberOfPhysicalMonitorsFromHMONITOR, [C.c_void_p, C.POINTER(U32)]),
            (self.dxva.GetPhysicalMonitorsFromHMONITOR, [C.c_void_p, U32, C.POINTER(PhysicalMonitor)]),
            (self.dxva.DestroyPhysicalMonitors, [U32, C.POINTER(PhysicalMonitor)]),
            (self.dxva.GetMonitorCapabilities, [C.c_void_p, C.POINTER(U32), C.POINTER(U32)]),
            (self.dxva.GetMonitorBrightness, [C.c_void_p, C.POINTER(U32), C.POINTER(U32), C.POINTER(U32)]),
            (self.dxva.SetMonitorBrightness, [C.c_void_p, U32]),
            (self.dxva.GetVCPFeatureAndVCPFeatureReply,
             [C.c_void_p, C.c_ubyte, C.POINTER(I32), C.POINTER(U32), C.POINTER(U32)]),
            (self.dxva.SetVCPFeature, [C.c_void_p, C.c_ubyte, U32]))
        for function, arguments in signatures:
            function.argtypes, function.restype = arguments, I32

    @staticmethod
    def check(success):
        if not success:
            raise C.WinError(C.get_last_error())

    def read_brightness(self, handle, low_level=False):
        minimum, current, maximum = U32(), U32(), U32()
        if low_level:
            kind = I32()
            self.check(self.dxva.GetVCPFeatureAndVCPFeatureReply(
                handle, 0x10, C.byref(kind), C.byref(current), C.byref(maximum)))
            if kind.value != 1:
                raise ValueError('The brightness VCP is not a set-parameter control.')
        else:
            self.check(self.dxva.GetMonitorBrightness(handle, C.byref(minimum), C.byref(current), C.byref(maximum)))
        if not minimum.value <= current.value <= maximum.value or maximum.value <= minimum.value:
            raise ValueError('The monitor returned an invalid brightness range.')
        return minimum.value, current.value, maximum.value

    def transfer(self, device, percent=None, prefer_vcp=False):
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
            raise InputIdentityError('The output must identify exactly one logical monitor.')
        count = U32()
        self.check(self.dxva.GetNumberOfPhysicalMonitorsFromHMONITOR(matches[0], C.byref(count)))
        if count.value != 1:
            raise InputIdentityError('The output must identify exactly one physical monitor.')
        physical = (PhysicalMonitor * 1)()
        self.check(self.dxva.GetPhysicalMonitorsFromHMONITOR(matches[0], 1, physical))
        try:
            caps, temperatures = U32(), U32()
            low_level = prefer_vcp
            checking_capabilities = not prefer_vcp
            try:
                if prefer_vcp:
                    self.trace.append({'stage': 'capability', 'result': 'skipped', 'elapsedMs': 0,
                                       'reason': 'Same output previously required VCP brightness.'})
                else:
                    measure(self.trace, 'capability', lambda: self.check(self.dxva.GetMonitorCapabilities(
                        physical[0].handle, C.byref(caps), C.byref(temperatures))))
                    if not caps.value & 2:
                        low_level = True
                        self.trace.append({'stage': 'brightness-path', 'result': 'skipped', 'elapsedMs': 0,
                                           'reason': 'High-level brightness is not reported; probing VCP 0x10.'})
                checking_capabilities = False
                minimum, current, maximum = measure(self.trace, 'initial-read', self.read_brightness,
                                                    physical[0].handle, low_level)
            except OSError as error:
                allowed = MCCS_COMPATIBILITY_ERRORS + (0xc0262589, 0xc026258a) if checking_capabilities else MCCS_COMPATIBILITY_ERRORS
                if low_level or getattr(error, 'winerror', 0) & 0xffffffff not in allowed:
                    raise
                low_level = True
                minimum, current, maximum = measure(self.trace, 'initial-read', self.read_brightness,
                                                    physical[0].handle, True)
            desired = round(minimum + (maximum - minimum) * percent / 100) if percent is not None else current
            changed = desired != current
            if changed:
                bounds = minimum, maximum
                if low_level:
                    measure(self.trace, 'write', lambda: self.check(self.dxva.SetVCPFeature(physical[0].handle, 0x10, desired)))
                else:
                    measure(self.trace, 'write', lambda: self.check(self.dxva.SetMonitorBrightness(physical[0].handle, desired)))
                def confirm():
                    values = self.read_brightness(physical[0].handle, low_level)
                    if values[1] != desired or (values[0], values[2]) != bounds:
                        raise RuntimeError('DDC/CI brightness write was not confirmed; no retry was sent.')
                    return values
                minimum, current, maximum = measure(self.trace, 'confirm', confirm)
            return {'minimum': minimum, 'maximum': maximum, 'current': current,
                    'percent': round((current - minimum) * 100 / (maximum - minimum)),
                    'levels': [], 'changed': changed, 'ddcMethod': 'vcp' if low_level else 'high-level'}
        finally:
            self.check(self.dxva.DestroyPhysicalMonitors(1, physical))


class NativeControls:
    def __init__(self, display=None, color=None, ddc=None, windows=windows_brightness, clock=time.monotonic, sleep=time.sleep,
                 factor_reader=read_factor, legacy_hdr_reader=legacy_hdr_info):
        self.display = display or WindowsApi()
        self.color = color or WindowsColorApi()
        self.ddc = ddc
        self.windows = windows
        self.factor_reader = factor_reader
        self.legacy_hdr_reader = legacy_hdr_reader
        self.clock, self.sleep = clock, sleep
        self.trace = []
        self.prefer_vcp = False

    def endpoint(self, target=None):
        return measure(self.trace, 'endpoint', self._endpoint, target)

    def _endpoint(self, target=None):
        paths = self.display.query(QDC_ONLY_ACTIVE_PATHS).paths
        if len(paths) != 1 or not paths[0].flags & 1 or not paths[0].target.available:
            raise InputIdentityError('Enable exactly one display output before using Other tools.')
        path = paths[0]
        identity = self.display.device_path(path)
        if not identity or target and (key(path.target) != target['targetKey'] or identity != target['monitorDevicePath']):
            raise InputIdentityError('Active display identity changed; no operation was repeated.')
        return path, identity

    def read_hdr(self, path):
        state = measure(self.trace, 'hdr', self.color.get, path)
        supported, enabled = state['supported'], state['hdrActive']
        error = 'Windows policy prevents HDR control.' if state['limitedByPolicy'] else ''
        if state.get('legacyAdvancedColor'):
            available, kind = measure(self.trace, 'legacy-hdr', self.legacy_hdr_reader, self.display, path)
            enabled = kind == 2
            if kind == 1 or enabled != state['enabled']:
                error = error or 'Legacy HDR control requires a confirmed HDR or standard SDR mode.'
            supported = supported and available
        return state, {'supported': bool(supported) and not error, 'enabled': enabled, 'error': error}

    def hdr_state(self, path):
        try:
            return self.read_hdr(path)[1]
        except (OSError, ValueError, RuntimeError) as error:
            return {'supported': False, 'enabled': None, 'error': str(error)}

    def brightness(self, path, identity, hdr, percent=None):
        internal = path.target.technology in INTERNAL
        result = {'supported': False, 'writable': False, 'method': 'windows' if internal else 'ddc',
                  'minimum': None, 'maximum': None, 'current': None, 'percent': None, 'levels': [], 'error': ''}
        if not internal and percent is not None:
            hdr = self.hdr_state(path)
        if not internal and hdr['enabled'] is not False:
            result['error'] = 'External display brightness is disabled while HDR is on or its state is unavailable.'
            if percent is not None:
                raise ValueError(result['error'])
            return result
        try:
            if internal:
                values = measure(self.trace, 'windows-brightness', self.windows, identity, percent)
                result['ddcMethod'] = 'windows'
            else:
                name = SourceName()
                name.header = Header(1, C.sizeof(name), path.source.adapter, path.source.id)
                WindowsApi.check(self.display.dll.DisplayConfigGetDeviceInfo(C.byref(name.header)))
                self.endpoint({'targetKey': key(path.target), 'monitorDevicePath': identity})
                ddc = self.ddc or WindowsBrightness(trace=self.trace)
                values = ddc.transfer(name.device, percent, True) if self.prefer_vcp else ddc.transfer(name.device, percent)
                if 'ddcMethod' in values:
                    result['ddcMethod'] = values['ddcMethod']
            result.update({k: values[k] for k in ('minimum', 'maximum', 'current', 'percent', 'levels')})
            result.update(supported=True, writable=True, changed=values.get('changed', False))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            if percent is not None:
                raise
            result['error'] = str(error)
            if self.prefer_vcp and getattr(error, 'winerror', 0) & 0xffffffff in (0xc0262589, 0xc026258a):
                result['_vcpReadTransient'] = True
        return result

    def run(self, request):
        self.trace = []
        self.prefer_vcp = False
        started = time.perf_counter()
        result = self._run(request)
        controls = result if request['command'] in ('get_display_controls', 'get_brightness_factor') else result['displayControls']
        controls.update(controlTrace=self.trace, controlElapsedMs=(time.perf_counter() - started) * 1000)
        return result

    def _run(self, request):
        command = request['command']
        target = request if command != 'get_display_controls' else None
        path, identity = self.endpoint(target)
        hint = request.get('_brightnessVcp')
        self.prefer_vcp = (isinstance(hint, dict) and hint.get('targetKey') == key(path.target)
                           and hint.get('monitorDevicePath') == identity and path.target.technology not in INTERNAL)
        name = TargetName()
        name.header = Header(2, C.sizeof(name), path.target.adapter, path.target.id)
        WindowsApi.check(self.display.dll.DisplayConfigGetDeviceInfo(C.byref(name.header)))
        target = {'targetKey': key(path.target), 'monitorDevicePath': identity,
                  'name': bytes(name.name).decode('utf-16-le').split('\0', 1)[0],
                  'connection': {5: 'HDMI', 6: 'LVDS', 10: 'DisplayPort / USB-C', 11: 'eDP',
                                 13: 'Embedded UDI', 0x80000000: 'Internal'}.get(path.target.technology, 'Other'),
                  'internal': path.target.technology in INTERNAL, 'technology': int(path.target.technology)}
        hdr = self.hdr_state(path)
        if command == 'get_brightness_factor':
            if path.target.technology not in FACTOR_TECHNOLOGIES or hdr['enabled'] is not True or not hdr['supported']:
                raise ValueError('Brightness factor requires one eDP or Internal output with HDR enabled.')
            source = (path.source.adapter.high, path.source.adapter.low, path.source.id)
            before = measure(self.trace, 'brightness-before-factor', self.windows, identity)
            values = measure(self.trace, 'fresh-factor', self.factor_reader, self.display, path, identity)
            path, _ = self.endpoint(target)
            after = measure(self.trace, 'brightness-after-factor', self.windows, identity)
            path, _ = self.endpoint(target)
            after_hdr = self.hdr_state(path)
            path, _ = self.endpoint(target)
            if (path.target.technology != target['technology'] or after_hdr['enabled'] is not True or not after_hdr['supported']
                    or source != (path.source.adapter.high, path.source.adapter.low, path.source.id)
                    or before['percent'] != after['percent']):
                raise ValueError('Brightness or HDR changed during factor sampling; refresh before adjusting.')
            return {'target': target, 'brightnessPercent': after['percent'], **values}
        changed = False
        if command == 'set_display_hdr':
            if not hdr['supported'] or type(hdr['enabled']) is not bool:
                raise ValueError(hdr['error'] or 'HDR control is unsupported.')
            enabled = request['enabled']
            if hdr['enabled'] != enabled:
                path, _ = self.endpoint(target)
                state, before = self.read_hdr(path)
                if not before['supported'] or before['enabled'] != hdr['enabled']:
                    raise ValueError('Windows HDR support changed before writing; no command was sent.')
                path, _ = self.endpoint(target)
                self.color.set(path, state, enabled)
                changed = True
                deadline = self.clock() + 5
                while True:
                    path, _ = self.endpoint(target)
                    hdr = self.hdr_state(path)
                    if hdr['enabled'] is enabled:
                        break
                    if self.clock() >= deadline:
                        raise RuntimeError('HDR write was sent once but its state was not confirmed within five seconds.')
                    self.sleep(.2)
        if command == 'set_display_brightness':
            self.endpoint(target)
            if request.get('expectedHdr') is True:
                path, _ = self.endpoint(target)
                fresh_hdr = self.hdr_state(path)
                if path.target.technology not in FACTOR_TECHNOLOGIES or fresh_hdr['enabled'] is not True or not fresh_hdr['supported']:
                    raise ValueError('Auto adjustment requires the same eDP or Internal output with HDR still enabled; no write was sent.')
            brightness = self.brightness(path, identity, hdr, request['percent'])
            changed = brightness.pop('changed', False)
        else:
            brightness = self.brightness(path, identity, hdr)
            brightness.pop('changed', None)
        path, _ = self.endpoint(target)
        final_hdr = self.hdr_state(path)
        self.endpoint(target)
        if request.get('expectedHdr') is True and (path.target.technology != target['technology'] or final_hdr['enabled'] is not True):
            raise RuntimeError('HDR changed during brightness confirmation; the result is unconfirmed and no write was repeated.')
        if command == 'set_display_hdr' and final_hdr['enabled'] is not request['enabled']:
            raise RuntimeError('HDR state changed during confirmation; no operation was repeated.')
        if not target['internal'] and final_hdr['enabled'] is not False:
            if command == 'set_display_brightness':
                raise RuntimeError('HDR state changed during brightness confirmation; the result is unconfirmed and no write was repeated.')
            brightness = self.brightness(path, identity, final_hdr)
        elif not target['internal'] and final_hdr != hdr and not brightness['writable']:
            brightness['error'] = 'HDR changed during the query. Refresh controls before adjusting brightness.'
        controls = {'target': target, 'hdr': final_hdr, 'brightness': brightness}
        return controls if command == 'get_display_controls' else {
            'command': command, 'targetKey': target['targetKey'], 'monitorDevicePath': identity,
            'changed': changed, 'displayControls': controls}


def control_request(request):
    started = time.perf_counter()
    try:
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker'],
            input=json.dumps(request).encode('utf-8'), capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as error:
        error.controlElapsedMs = (time.perf_counter() - started) * 1000
        error.controlTrace = [{'stage': 'worker', 'result': 'error', 'elapsedMs': error.controlElapsedMs,
                               'reason': 'Display-control worker timed out; no retry was sent.'}]
        raise
    if result.returncode or len(result.stdout) > 65536:
        raise ControlError('Display-control worker failed; outcome may be unknown. No retry was sent.', [],
                           (time.perf_counter() - started) * 1000)
    reply = json.loads(result.stdout.decode('utf-8'))
    elapsed = (time.perf_counter() - started) * 1000
    if reply.get('ok') is not True:
        trace = reply.get('controlTrace', [])
        trace.append({'stage': 'worker', 'result': 'error', 'elapsedMs': elapsed,
                      'reason': reply.get('error', 'Display control failed.')[:1024]})
        raise ControlError(reply.get('error', 'Display control failed.'), trace, elapsed)
    result = reply['result']
    controls = result if request['command'] in ('get_display_controls', 'get_brightness_factor') else result['displayControls']
    controls['controlElapsedMs'] = elapsed
    controls['controlTrace'].append({'stage': 'worker', 'result': 'ok', 'elapsedMs': elapsed})
    return result


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('Only the fixed display-control worker entry point is supported.')
    native = None
    try:
        native = NativeControls()
        request = json.loads(sys.stdin.buffer.read(16385))
        reply = {'ok': True, 'result': native.run(request)}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        reply = {'ok': False, 'error': str(error), 'controlTrace': native.trace if native else []}
    print(json.dumps(reply, ensure_ascii=True))
