"""Run the actual PowerShell brightness script with isolated CIM functions."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from displayhdr_controls import WMI_SCRIPT


class WindowsBrightnessScriptTests(unittest.TestCase):
    def invoke(self, reply='@{}', update=True, percent=67):
        prefix = r'''
$script:brightness = 40
$script:writes = 0
$script:reads = 0
function Get-CimInstance {
    param($Namespace, $ClassName)
    if ($Namespace -ne 'root/wmi') { throw 'Unexpected namespace' }
    if ($ClassName -eq 'WmiMonitorBrightness') {
        $script:reads++
        [pscustomobject]@{Active=$true; InstanceName='DISPLAY\MOCK\ID_0'; Level=@(0..100); CurrentBrightness=$script:brightness}
    } elseif ($ClassName -eq 'WmiMonitorBrightnessMethods') {
        [pscustomobject]@{Active=$true; InstanceName='DISPLAY\MOCK\ID_0'}
    } else { throw 'Unexpected class' }
}
function Invoke-CimMethod {
    param($InputObject, $MethodName, $Arguments)
    if ($MethodName -ne 'WmiSetBrightness' -or $Arguments.Timeout -ne 0) { throw 'Unexpected write' }
    $script:writes++
    __UPDATE__
    __REPLY__
}
$result = & {
'''.replace('__UPDATE__', '$script:brightness = [int]$Arguments.Brightness' if update else '')
        script = prefix.replace('__REPLY__', reply) + WMI_SCRIPT + r'''
} | ConvertFrom-Json
@{result=$result; writes=$script:writes; reads=$script:reads} | ConvertTo-Json -Compress -Depth 5
'''
        executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        completed = subprocess.run([str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
            input=json.dumps({'instance': r'DISPLAY\MOCK\ID', 'percent': percent}).encode(),
            capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))
        return json.loads(completed.stdout.decode('utf-8-sig'))

    def test_missing_return_value_succeeds_only_after_matching_readback(self):
        reply = self.invoke()
        self.assertEqual(reply['result']['current'], 67)
        self.assertEqual((reply['writes'], reply['reads']), (1, 2))

    def test_null_return_value_also_requires_matching_readback(self):
        reply = self.invoke('[pscustomobject]@{ReturnValue=$null}')
        self.assertEqual(reply['result']['current'], 67)
        self.assertEqual(reply['writes'], 1)

    def test_explicit_zero_preserves_success_path(self):
        self.assertEqual(self.invoke('[pscustomobject]@{ReturnValue=0}')['result']['current'], 67)

    def test_explicit_error_is_not_ignored_even_when_brightness_changed(self):
        reply = self.invoke('[pscustomobject]@{ReturnValue=7}')
        self.assertIn('returned error 7', reply['result']['error'])
        self.assertEqual(reply['writes'], 1)

    def test_missing_status_with_mismatched_readback_never_claims_success_or_rewrites(self):
        reply = self.invoke(update=False)
        self.assertIn('not confirmed', reply['result']['error'])
        self.assertEqual((reply['writes'], reply['reads']), (1, 2))

    def test_same_brightness_does_not_write(self):
        reply = self.invoke(percent=40)
        self.assertEqual(reply['result']['current'], 40)
        self.assertFalse(reply['result']['changed'])
        self.assertEqual(reply['writes'], 0)


if __name__ == '__main__':
    unittest.main()
