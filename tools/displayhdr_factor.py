"""Fresh, read-only luminance metadata for one explicitly identified output.

Interfaces and layouts follow Microsoft dxgi.h/dxgi1_6.h and DisplayMonitor.
This module never starts a renderer or writes a display setting.
"""
import base64
import ctypes as C
import json
import math
import os
from pathlib import Path
import subprocess
import uuid

from displayhdr_display_paths import Luid, I32, U32
from displayhdr_monitor_input import SourceName
from displayhdr_display_paths import Header, WindowsApi


class AdapterDesc(C.Structure):
    _fields_ = [('description', C.c_wchar * 128), ('vendor', U32), ('device', U32),
                ('subsystem', U32), ('revision', U32), ('videoMemory', C.c_size_t),
                ('systemMemory', C.c_size_t), ('sharedMemory', C.c_size_t), ('luid', Luid), ('flags', U32)]


class OutputDesc(C.Structure):
    _fields_ = [('device', C.c_wchar * 32), ('rect', I32 * 4), ('attached', I32),
                ('rotation', I32), ('monitor', C.c_void_p), ('bits', U32), ('colorSpace', I32),
                ('red', C.c_float * 2), ('green', C.c_float * 2), ('blue', C.c_float * 2),
                ('white', C.c_float * 2), ('minimum', C.c_float), ('maximum', C.c_float), ('fullFrame', C.c_float)]


def guid(value):
    return (C.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le)


def method(pointer, index, arguments, *values):
    table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(I32, C.c_void_p, *arguments)(table[index])(pointer, *values)


def check(result):
    if result < 0:
        raise OSError(f'DXGI metadata query failed: 0x{result & 0xffffffff:08X}.')


def release(pointer):
    if pointer:
        method(pointer, 2, [])


def dxgi_luminance(adapter_luid, device):
    """Use a new factory and exactly one adapter/output match on every call."""
    factory = C.c_void_p()
    dll = C.WinDLL('dxgi')
    dll.CreateDXGIFactory1.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
    dll.CreateDXGIFactory1.restype = I32
    check(dll.CreateDXGIFactory1(guid('770aae78-f26f-4dba-a829-253c83d1b387'), C.byref(factory)))
    matches = []
    try:
        for adapter_index in range(64):
            adapter = C.c_void_p()
            result = method(factory, 12, [U32, C.POINTER(C.c_void_p)], adapter_index, C.byref(adapter))
            if result & 0xffffffff == 0x887a0002:
                break
            check(result)
            try:
                description = AdapterDesc()
                check(method(adapter, 10, [C.POINTER(AdapterDesc)], C.byref(description)))
                if (description.luid.high, description.luid.low) != adapter_luid:
                    continue
                for output_index in range(64):
                    output, output6 = C.c_void_p(), C.c_void_p()
                    result = method(adapter, 7, [U32, C.POINTER(C.c_void_p)], output_index, C.byref(output))
                    if result & 0xffffffff == 0x887a0002:
                        break
                    check(result)
                    try:
                        desc = OutputDesc()
                        check(method(output, 7, [C.POINTER(OutputDesc)], C.byref(desc)))
                        if not desc.attached or desc.device.casefold() != device.casefold():
                            continue
                        check(method(output, 0, [C.c_void_p, C.POINTER(C.c_void_p)],
                                     guid('068346e8-aaec-4b84-add7-137f513f77a1'), C.byref(output6)))
                        desc = OutputDesc()
                        check(method(output6, 27, [C.POINTER(OutputDesc)], C.byref(desc)))
                        if not desc.attached or desc.device.casefold() != device.casefold() or desc.colorSpace != 12:
                            raise ValueError('Fresh DXGI output identity or HDR10 color space changed.')
                        matches.append(float(desc.maximum))
                    finally:
                        release(output6)
                        release(output)
                else:
                    raise RuntimeError('DXGI output enumeration exceeded its bound.')
            finally:
                release(adapter)
        else:
            raise RuntimeError('DXGI adapter enumeration exceeded its bound.')
    finally:
        release(factory)
    if len(matches) != 1:
        raise ValueError('A unique fresh DXGI output matching the active endpoint was not found.')
    return matches[0]


RAW_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Devices.Display.DisplayMonitor, Windows.Devices.Display, ContentType=WindowsRuntime]
    $operation = [Windows.Devices.Display.DisplayMonitor]::FromInterfaceIdAsync($request.identity)
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
        $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    if ($null -eq $asTask) { throw 'Windows Runtime task conversion is unavailable.' }
    $task = $asTask.MakeGenericMethod([Windows.Devices.Display.DisplayMonitor]).Invoke($null, @($operation))
    if (-not $task.Wait(2000)) { throw 'DisplayMonitor query timed out.' }
    $monitor = $task.Result
    if ($null -eq $monitor) { throw 'DisplayMonitor did not return the requested monitor.' }
    @{rawMaxLuminance=[double]$monitor.MaxLuminanceInNits} | ConvertTo-Json -Compress
} catch {
    @{error=$_.Exception.Message} | ConvertTo-Json -Compress
}
'''


def raw_luminance(identity):
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(RAW_SCRIPT.encode('utf-16-le')).decode('ascii')],
        input=json.dumps({'identity': identity}).encode('utf-8'), capture_output=True, timeout=4,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or len(result.stdout) > 65536:
        raise RuntimeError('DisplayMonitor worker failed or exceeded its output limit.')
    reply = json.loads(result.stdout.decode('utf-8-sig'))
    if 'error' in reply:
        raise RuntimeError(reply['error'])
    return reply.get('rawMaxLuminance')


def read_factor(display, path, identity):
    source = SourceName()
    source.header = Header(1, C.sizeof(source), path.source.adapter, path.source.id)
    WindowsApi.check(display.dll.DisplayConfigGetDeviceInfo(C.byref(source.header)))
    raw = raw_luminance(identity)
    adjusted = dxgi_luminance((path.source.adapter.high, path.source.adapter.low), source.device)
    if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in (raw, adjusted)):
        raise ValueError('Luminance metadata must be finite and positive.')
    # The official renderer divides two float32 values, then promotes the result to double.
    raw, adjusted = C.c_float(raw).value, C.c_float(adjusted).value
    if any(not math.isfinite(value) or value <= 0 for value in (raw, adjusted)):
        raise ValueError('Luminance metadata is outside the finite float32 range.')
    factor = C.c_float(raw / adjusted).value
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError('Brightness factor must be finite and positive.')
    return {'factor': factor, 'rawMaxLuminance': raw, 'adjustedMaxLuminance': adjusted}
