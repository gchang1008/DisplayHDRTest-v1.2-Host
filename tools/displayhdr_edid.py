"""Read complete, endpoint-specific EDID blocks without changing display settings."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import winreg


# Microsoft WmiMonitorDescriptorMethods.WmiGetMonitorRawEEdidV1Block returns
# one 128-byte block. Keep each successful block if a later block fails.
WMI_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$clock = [Diagnostics.Stopwatch]::StartNew()
try {
    $instance = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $monitors = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorDescriptorMethods |
        Where-Object { $_.Active -and (($_.InstanceName -replace '_\d+$', '') -ieq $instance) })
    if ($monitors.Count -ne 1) { throw 'A unique active WMI monitor matching the output was not found.' }
    for ($index = 0; $index -lt 256; $index++) {
        $clock.Restart()
        try {
            $result = Invoke-CimMethod -InputObject $monitors[0] -MethodName WmiGetMonitorRawEEdidV1Block -Arguments @{BlockId=[byte]$index}
        } catch {
            [Console]::Out.WriteLine((@{end=$index;elapsedMs=$clock.Elapsed.TotalMilliseconds;reason=$_.Exception.Message} | ConvertTo-Json -Compress))
            break
        }
        $status = $result.ReturnValue
        $success = if ($status -is [bool]) { $status } else {
            ($status -is [int] -or $status -is [uint32] -or $status -is [long] -or $status -is [uint64]) -and $status -eq 0
        }
        if (-not $success -or $result.BlockType -eq 0) {
            [Console]::Out.WriteLine((@{end=$index;blockType=$result.BlockType;elapsedMs=$clock.Elapsed.TotalMilliseconds;reason="EDID block $index returned WMI status $status, block type $($result.BlockType)."} | ConvertTo-Json -Compress))
            break
        }
        if ($result.BlockType -notin @(1, 2, 255)) { throw "EDID block $index returned an invalid WMI block type." }
        $block = [byte[]]$result.BlockContent
        if ($block.Length -ne 128) { throw "EDID block $index did not contain 128 bytes." }
        [Console]::Out.WriteLine((@{block=$index;blockType=$result.BlockType;elapsedMs=$clock.Elapsed.TotalMilliseconds;data=[Convert]::ToBase64String($block)} | ConvertTo-Json -Compress))
        [Console]::Out.Flush()
    }
    if ($index -eq 256) { throw 'WMI EDID reading reached the 256-block limit; no further block can be queried.' }
} catch {
    [Console]::Out.WriteLine((@{error=$_.Exception.Message;blockType=$result.BlockType;byteLength=$result.BlockContent.Length;elapsedMs=$clock.Elapsed.TotalMilliseconds} | ConvertTo-Json -Compress))
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


def wmi_edid(device_path, trace=None):
    trace = trace if trace is not None else []
    started = time.perf_counter()
    instance = monitor_instance(device_path)
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = [str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
               base64.b64encode(WMI_SCRIPT.encode('utf-16-le')).decode('ascii')]
    warnings = []
    failure = None
    try:
        result = subprocess.run(command, input=json.dumps(instance).encode('utf-8'),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW)
        output = result.stdout
        if result.returncode:
            warnings.append('WMI EDID reader exited with code ' + str(result.returncode) + '.')
            failure = ('error', warnings[-1])
    except subprocess.TimeoutExpired as error:
        output = error.stdout or b''
        warnings.append('WMI EDID reading exceeded 8 seconds; available blocks were retained.')
        failure = ('timeout', warnings[-1])
    blocks = []
    stopped = False
    for line in output.decode('utf-8-sig', errors='replace').splitlines():
        try:
            row = json.loads(line)
            event = {'stage': 'wmi', 'block': len(blocks), 'elapsedMs': row.get('elapsedMs', 0)}
            if type(row.get('blockType')) is int:
                event['blockType'] = row['blockType']
            if type(row.get('byteLength')) is int:
                event['byteLength'] = row['byteLength']
            if 'end' in row:
                if row['end'] != len(blocks):
                    raise ValueError('Unexpected WMI EDID end block.')
                data = b''.join(blocks)
                expected = expected_length(data)
                if expected is None or len(data) < expected:
                    warnings.append('WMI EDID reading stopped: ' + str(row['reason']))
                trace.append({**event, 'result': 'end', 'reason': str(row['reason'])[:1024]})
                stopped = True
                break
            if 'error' in row:
                warnings.append(str(row['error']))
                trace.append({**event, 'result': 'limit' if len(blocks) == 256 else 'error',
                              'reason': str(row['error'])[:1024]})
                stopped = True
                break
            block = base64.b64decode(row['data'], validate=True)
            if row['block'] != len(blocks) or len(block) != 128:
                raise ValueError('Noncontiguous or malformed WMI EDID block.')
            blocks.append(block)
            trace.append({**event, 'result': 'read', 'byteLength': len(block)})
        except (ValueError, KeyError, TypeError) as error:
            warnings.append('WMI EDID response could not be read: ' + str(error))
            trace.append({'stage': 'wmi', 'block': len(blocks), 'result': 'error',
                          'elapsedMs': 0, 'reason': warnings[-1][:1024]})
            stopped = True
            break
    if failure or not stopped:
        result, reason = failure or ('end', 'WMI reader exited without a stop record.')
        trace.append({'stage': 'wmi', 'block': len(blocks), 'result': result,
                      'elapsedMs': (time.perf_counter() - started) * 1000, 'reason': reason[:1024]})
    return b''.join(blocks), warnings


def expected_length(data):
    if len(data) < 128:
        return None
    extensions = data[126]
    if extensions and len(data) >= 256:
        cta = data[128:256]
        size = cta[4] & 31
        if (cta[0] == 2 and cta[1] >= 3 and 7 <= cta[2] <= 127
                and cta[4] >> 5 == 7 and size >= 2 and 5 + size <= cta[2]
                and cta[5] == 0x78 and cta[6]):
            extensions = cta[6]
    return (extensions + 1) * 128


def describe_edid(data, source, warnings=()):
    warnings = list(warnings)
    expected = expected_length(data)
    complete = expected is not None and len(data) == expected
    checksums = bool(data) and len(data) % 128 == 0 and all(
        sum(data[index:index + 128]) % 256 == 0 for index in range(0, len(data), 128))
    if not complete:
        warnings.append(f'EDID length differs from declaration: received {len(data)} bytes; expected {expected if expected is not None else "unknown"}.')
    if data[:8] != bytes.fromhex('00ffffffffffff00'):
        warnings.append('EDID base block header is missing or invalid.')
    if not checksums:
        warnings.append('EDID block checksum validation failed or blocks are incomplete.')
    return {'dataBase64': base64.b64encode(data).decode('ascii'), 'source': source,
            'byteLength': len(data), 'expectedLength': expected, 'complete': complete,
            'checksumsValid': checksums, 'warnings': warnings}


def read_edid(device_path):
    started = time.perf_counter()
    trace = []
    warnings = []
    try:
        data, warnings = wmi_edid(device_path, trace)
    except (OSError, ValueError) as error:
        data = b''
        warnings.append('WMI EDID reading failed: ' + str(error))
        trace.append({'stage': 'wmi', 'block': 0, 'result': 'error',
                      'elapsedMs': (time.perf_counter() - started) * 1000, 'reason': str(error)[:1024]})
    source = 'wmi' if data else 'unavailable'
    if len(data) < (expected_length(data) or 128):
        cached_started = time.perf_counter()
        try:
            cached = registry_edid(device_path)
            if data and not cached.startswith(data):
                warnings.append('Registry EDID differs from WMI; cached data was not substituted.')
                outcome, reason = 'skipped', warnings[-1]
            elif len(cached) > len(data):
                data, source = cached, 'registry'
                warnings.append('Using Windows registry EDID fallback; this is cached driver data, not a fresh physical read.')
                outcome, reason = 'used', warnings[-1]
            else:
                outcome, reason = 'skipped', 'Registry EDID does not contain more bytes than WMI.'
            trace.append({'stage': 'registry', 'result': outcome, 'byteLength': len(cached),
                          'elapsedMs': (time.perf_counter() - cached_started) * 1000, 'reason': reason})
        except (OSError, ValueError) as error:
            warnings.append('Registry EDID fallback failed: ' + str(error))
            trace.append({'stage': 'registry', 'result': 'error',
                          'elapsedMs': (time.perf_counter() - cached_started) * 1000, 'reason': str(error)[:1024]})
    else:
        trace.append({'stage': 'registry', 'result': 'skipped', 'elapsedMs': 0,
                      'reason': 'WMI data already meets or exceeds the declared length.'})
    result = describe_edid(data, source, warnings)
    result.update(readTrace=trace, readElapsedMs=(time.perf_counter() - started) * 1000)
    return result
