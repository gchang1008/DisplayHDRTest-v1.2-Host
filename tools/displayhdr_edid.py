"""Read complete, endpoint-specific EDID blocks without changing display settings."""
import base64
import json
import os
from pathlib import Path
import subprocess
import winreg


# Microsoft WmiMonitorDescriptorMethods.WmiGetMonitorRawEEdidV1Block returns
# one 128-byte block. Keep each successful block if a later block fails.
WMI_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
try {
    $instance = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $monitors = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorDescriptorMethods |
        Where-Object { $_.Active -and (($_.InstanceName -replace '_\d+$', '') -ieq $instance) })
    if ($monitors.Count -ne 1) { throw 'A unique active WMI monitor matching the output was not found.' }
    $count = 1
    for ($index = 0; $index -lt $count; $index++) {
        $result = Invoke-CimMethod -InputObject $monitors[0] -MethodName WmiGetMonitorRawEEdidV1Block -Arguments @{BlockId=[byte]$index}
        $status = $result.ReturnValue
        $success = if ($status -is [bool]) { $status } else {
            ($status -is [int] -or $status -is [uint32] -or $status -is [long] -or $status -is [uint64]) -and $status -eq 0
        }
        if (-not $success) { throw "EDID block $index returned WMI error $status." }
        $block = [byte[]]$result.BlockContent
        if ($block.Length -ne 128) { throw "EDID block $index did not contain 128 bytes." }
        [Console]::Out.WriteLine((@{block=$index;data=[Convert]::ToBase64String($block)} | ConvertTo-Json -Compress))
        [Console]::Out.Flush()
        if ($index -eq 0) { $count = 1 + [int]$block[126] }
    }
} catch {
    [Console]::Out.WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))
}
'''


def monitor_instance(device_path):
    parts = device_path.split('#')
    if len(parts) != 4 or parts[0].upper() != r'\\?\DISPLAY' or not parts[1] or not parts[2]:
        raise ValueError('Invalid monitor device path for EDID reading.')
    return '\\'.join(('DISPLAY', parts[1], parts[2]))


def registry_edid(device_path):
    instance = monitor_instance(device_path)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            'SYSTEM\\CurrentControlSet\\Enum\\' + instance + '\\Device Parameters') as registry:
        value, kind = winreg.QueryValueEx(registry, 'EDID')
    if kind != winreg.REG_BINARY or not isinstance(value, bytes):
        raise ValueError('Windows registry EDID is not binary data.')
    return value


def wmi_edid(device_path):
    instance = monitor_instance(device_path)
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = [str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
               base64.b64encode(WMI_SCRIPT.encode('utf-16-le')).decode('ascii')]
    warnings = []
    try:
        result = subprocess.run(command, input=json.dumps(instance).encode('utf-8'),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW)
        output = result.stdout
        if result.returncode:
            warnings.append('WMI EDID reader exited with code ' + str(result.returncode) + '.')
    except subprocess.TimeoutExpired as error:
        output = error.stdout or b''
        warnings.append('WMI EDID reading exceeded 8 seconds; available blocks were retained.')
    blocks = []
    for line in output.decode('utf-8-sig', errors='replace').splitlines():
        try:
            row = json.loads(line)
            if 'error' in row:
                warnings.append(str(row['error']))
                break
            block = base64.b64decode(row['data'], validate=True)
            if row['block'] != len(blocks) or len(block) != 128:
                raise ValueError('Noncontiguous or malformed WMI EDID block.')
            blocks.append(block)
        except (ValueError, KeyError, TypeError) as error:
            warnings.append('WMI EDID response could not be read: ' + str(error))
            break
    return b''.join(blocks), warnings


def describe_edid(data, source, warnings=()):
    warnings = list(warnings)
    expected = (data[126] + 1) * 128 if len(data) >= 128 else None
    complete = expected is not None and len(data) == expected
    checksums = bool(data) and len(data) % 128 == 0 and all(
        sum(data[index:index + 128]) % 256 == 0 for index in range(0, len(data), 128))
    if not complete:
        warnings.append(f'Incomplete EDID: received {len(data)} bytes; expected {expected if expected is not None else "unknown"}.')
    if data[:8] != bytes.fromhex('00ffffffffffff00'):
        warnings.append('EDID base block header is missing or invalid.')
    if not checksums:
        warnings.append('EDID block checksum validation failed or blocks are incomplete.')
    return {'dataBase64': base64.b64encode(data).decode('ascii'), 'source': source,
            'byteLength': len(data), 'expectedLength': expected, 'complete': complete,
            'checksumsValid': checksums, 'warnings': warnings}


def read_edid(device_path):
    warnings = []
    try:
        data, warnings = wmi_edid(device_path)
    except (OSError, ValueError) as error:
        data = b''
        warnings.append('WMI EDID reading failed: ' + str(error))
    source = 'wmi' if data else 'unavailable'
    if len(data) < 128 or len(data) != (data[126] + 1) * 128:
        try:
            cached = registry_edid(device_path)
            if len(data) >= 128 and cached[:128] != data[:128]:
                warnings.append('Registry EDID base block differs from WMI; cached data was not substituted.')
            elif len(cached) > len(data):
                data, source = cached, 'registry'
                warnings.append('Using Windows registry EDID fallback; this is cached driver data, not a fresh physical read.')
        except (OSError, ValueError) as error:
            warnings.append('Registry EDID fallback failed: ' + str(error))
    return describe_edid(data, source, warnings)
