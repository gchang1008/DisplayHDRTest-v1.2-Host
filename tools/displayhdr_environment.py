"""Read the test computer and its active display configuration."""

import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import time
import winreg

from displayhdr_display_paths import Header, I32, U32, QDC_ONLY_ACTIVE_PATHS, key
from displayhdr_hdr_control import WindowsColorApi


COLOR_FORMATS = {0: "RGB", 1: "YCbCr 4:4:4", 2: "YCbCr 4:2:2", 3: "YCbCr 4:2:0",
                 4: "Intensity"}
VIRTUAL_MODE_AWARE = 0x10
VIRTUAL_REFRESH_RATE_AWARE = 0x40
PATH_SUPPORT_VIRTUAL_MODE = 0x08
PATH_ACTIVE = 0x01
# Win32_OperatingSystem.OperatingSystemSKU uses the PRODUCT_* values from winnt.h.
WINDOWS_EDITIONS = {
    4: "Enterprise", 27: "Enterprise N", 48: "Pro", 49: "Pro N",
    72: "Enterprise Evaluation", 84: "Enterprise N Evaluation", 98: "Home N",
    99: "Home China", 100: "Home Single Language", 101: "Home",
    121: "Education", 122: "Education N", 125: "Enterprise LTSC",
    126: "Enterprise LTSC N", 129: "Enterprise LTSC Evaluation",
    130: "Enterprise LTSC N Evaluation", 138: "Pro Single Language",
    161: "Pro for Workstations", 162: "Pro N for Workstations",
    164: "Pro Education", 165: "Pro Education N", 171: "Enterprise G",
    172: "Enterprise G N", 175: "Enterprise multi-session", 188: "IoT Enterprise",
    191: "IoT Enterprise LTSC", 202: "SE N", 203: "SE",
}

SYSTEM_QUERY = r"""
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$result = @{ warnings = @() }
if ($env:DISPLAYHDR_ADAPTER_INSTANCE) {
    try {
        $gpu = @(Get-CimInstance -ClassName Win32_VideoController -ErrorAction Stop |
                 Where-Object PNPDeviceID -eq $env:DISPLAYHDR_ADAPTER_INSTANCE)
        if ($gpu.Count -ne 1) { throw 'No unique video controller matches the active adapter.' }
        $result.gpuName = $gpu[0].Name
        $result.gpuDriverVersion = $gpu[0].DriverVersion
    } catch { $result.warnings += 'GPU details: ' + $_.Exception.Message }
}
try {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    $result.osSku = $os.OperatingSystemSKU
    $result.osProductType = $os.ProductType
    $result.osBuild = $os.BuildNumber
} catch { $result.warnings += 'OS details: ' + $_.Exception.Message }
try {
    $result.biosVersion = (Get-CimInstance -ClassName Win32_BIOS -ErrorAction Stop).SMBIOSBIOSVersion
} catch { $result.warnings += 'BIOS version: ' + $_.Exception.Message }
ConvertTo-Json -InputObject $result -Compress
"""


class AdapterName(C.Structure):
    _fields_ = [("header", Header), ("devicePath", C.c_wchar * 128)]


class DeviceInfo(C.Structure):
    # SP_DEVICE_INTERFACE_DATA and SP_DEVINFO_DATA share this layout.
    _fields_ = [("size", U32), ("guid", C.c_ubyte * 16), ("value", U32),
                ("reserved", C.c_size_t)]


def adapter_instance(api, path):
    adapter = AdapterName()
    adapter.header = Header(4, C.sizeof(adapter), path.target.adapter, 0)
    api.check(api.dll.DisplayConfigGetDeviceInfo(C.byref(adapter.header)))
    setup = C.WinDLL("setupapi", use_last_error=True)
    signatures = {
        "SetupDiCreateDeviceInfoList": ([C.c_void_p, C.c_void_p], C.c_void_p),
        "SetupDiOpenDeviceInterfaceW": ([C.c_void_p, C.c_wchar_p, U32, C.POINTER(DeviceInfo)], I32),
        "SetupDiGetDeviceInterfaceDetailW": ([C.c_void_p, C.POINTER(DeviceInfo), C.c_void_p, U32,
                                             C.POINTER(U32), C.POINTER(DeviceInfo)], I32),
        "SetupDiGetDeviceInstanceIdW": ([C.c_void_p, C.POINTER(DeviceInfo), C.c_wchar_p,
                                        U32, C.POINTER(U32)], I32),
        "SetupDiDestroyDeviceInfoList": ([C.c_void_p], I32),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(setup, name)
        function.argtypes, function.restype = argtypes, restype
    devices = setup.SetupDiCreateDeviceInfoList(None, None)
    if devices == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        interface = DeviceInfo(C.sizeof(DeviceInfo))
        if not setup.SetupDiOpenDeviceInterfaceW(devices, adapter.devicePath, 0, C.byref(interface)):
            raise C.WinError(C.get_last_error())
        # Only the associated device info is needed. SetupAPI reports the required
        # detail-buffer size and fills the device info even without a detail buffer.
        device = DeviceInfo(C.sizeof(DeviceInfo))
        size = U32()
        setup.SetupDiGetDeviceInterfaceDetailW(devices, C.byref(interface), None, 0,
                                               C.byref(size), C.byref(device))
        if C.get_last_error() != 122:
            raise C.WinError(C.get_last_error())
        instance = C.create_unicode_buffer(200)
        if not setup.SetupDiGetDeviceInstanceIdW(devices, C.byref(device), instance, len(instance), None):
            raise C.WinError(C.get_last_error())
        return instance.value
    finally:
        setup.SetupDiDestroyDeviceInfoList(devices)


def read_system(instance):
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    output = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", SYSTEM_QUERY],
        env={**os.environ, "DISPLAYHDR_ADAPTER_INSTANCE": instance},
        capture_output=True, check=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    result = json.loads(output.stdout.decode("utf-8-sig"))
    read_windows_release(result)
    return result


def read_windows_release(result):
    build = result.get("osBuild")
    sku = result.pop("osSku", None)
    product_type = result.pop("osProductType", None)
    if not isinstance(build, str) or not build.isdecimal():
        return
    edition = WINDOWS_EDITIONS.get(sku)
    if product_type == 1 and int(build) >= 10240 and edition:
        generation = 11 if int(build) >= 22000 else 10
        result["osName"] = f"Windows {generation} {edition}"
    else:
        result["warnings"].append(f"English Windows edition unavailable (SKU {sku}, product type {product_type}).")

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as registry:
            if winreg.QueryValueEx(registry, "CurrentBuildNumber")[0] != build:
                result["warnings"].append("Windows registry build differs from the running OS build.")
                return
            try:
                version, _ = winreg.QueryValueEx(registry, "DisplayVersion")
                if isinstance(version, str) and version.strip():
                    result["osVersion"] = version.strip()
                else:
                    result["warnings"].append("Windows DisplayVersion is empty or invalid.")
            except OSError:
                result["warnings"].append("Windows DisplayVersion is unavailable.")
            try:
                revision, _ = winreg.QueryValueEx(registry, "UBR")
                if type(revision) is int and revision >= 0:
                    result["osBuild"] = f"{build}.{revision}"
            except OSError:
                pass
    except OSError:
        result["warnings"].append("Windows release information is unavailable in the registry.")


def active_path(api, target, identity):
    for options in (VIRTUAL_MODE_AWARE | VIRTUAL_REFRESH_RATE_AWARE, VIRTUAL_MODE_AWARE, 0):
        flags = QDC_ONLY_ACTIVE_PATHS | options
        try:
            snapshot = api.query(flags)
            break
        except OSError as error:
            if not options or error.errno not in (50, 87):
                raise
    matches = [p for p in snapshot.paths if p.flags & PATH_ACTIVE and p.target.available
               and key(p.target) == target and api.device_path(p) == identity]
    if len(matches) != 1:
        raise ValueError("Requested display identity is no longer active.")
    return snapshot, matches[0], flags


def display_mode(snapshot, path, flags):
    index = path.source.modeIndex
    if flags & VIRTUAL_MODE_AWARE and path.flags & PATH_SUPPORT_VIRTUAL_MODE:
        index >>= 16
    resolution = None
    if index < len(snapshot.modes):
        mode = snapshot.modes[index]
        if mode.type == 1 and key(mode) == key(path.source):
            source = mode.data.source
            if source.width and source.height:
                resolution = f"{source.width}x{source.height}"
    refresh = path.target.refresh
    rate = refresh.numerator / refresh.denominator if refresh.numerator and refresh.denominator else None
    return resolution, rate


def read_environment(api, target, identity):
    started = time.monotonic()
    snapshot, path, flags = active_path(api, target, identity)
    resolution, rate = display_mode(snapshot, path, flags)
    result = {"resolution": resolution, "refreshRateHz": rate, "osVersion": None}
    warnings = []
    try:
        color = WindowsColorApi().get(path)
        result["colorDepthBpc"] = color["bitsPerColorChannel"] or None
        result["colorFormat"] = COLOR_FORMATS.get(color["colorEncoding"])
    except (OSError, RuntimeError) as error:
        warnings.append(f"Display color: {error}")
    instance = ""
    try:
        instance = adapter_instance(api, path)
    except OSError as error:
        warnings.append(f"Active GPU identity: {error}")
    try:
        system = read_system(instance)
        warnings.extend(system.get("warnings", []))
        for field in ("gpuName", "gpuDriverVersion", "osName", "osVersion", "osBuild", "biosVersion"):
            value = system.get(field)
            if isinstance(value, str) and value.strip():
                result[field] = value.strip()[:512]
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        warnings.append(f"Computer details: {error}")
    active_path(api, target, identity)
    return {**result, "warnings": [w[:512] for w in warnings],
            "readElapsedMs": round((time.monotonic() - started) * 1000, 3)}
