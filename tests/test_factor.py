"""Factor API, fresh metadata and guarded writes use isolated Windows doubles."""
import ctypes as C
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import displayhdr_controls as controls
import displayhdr_factor as factor
import displayhdr_server as server
import test_controls as fixtures


class FactorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ControlsTests()
        self.fixture.setUp()
        self.fixture.internal()
        self.fixture.color.enabled = True
        self.native = self.fixture.native
        self.reader = self.native.factor_reader = Mock(return_value={
            'factor': 1.01, 'rawMaxLuminance': 101, 'adjustedMaxLuminance': 100})
        self.request = {'command': 'get_brightness_factor', **self.fixture.target}

    def test_sample_has_matching_brightness_identity_and_native_trace(self):
        result = self.native.run(self.request)
        self.assertEqual(result['brightnessPercent'], 60)
        self.assertEqual(result['factor'], 1.01)
        self.assertEqual(result['target']['technology'], 11)
        self.assertEqual(self.fixture.windows.call_count, 2)
        self.assertTrue(all(call.args == ('monitor-1',) for call in self.fixture.windows.call_args_list))
        self.assertTrue({'brightness-before-factor', 'fresh-factor', 'brightness-after-factor'} <=
                        {row['stage'] for row in result['controlTrace']})
        self.fixture.native_ddc.transfer.assert_not_called()

    def test_hdr_off_or_ambiguous_is_rejected_without_metadata_or_brightness_read(self):
        for legacy in (False, True):
            self.fixture.color.enabled = False
            self.fixture.color.legacy = legacy
            with self.assertRaisesRegex(ValueError, 'HDR enabled'):
                self.native.run(self.request)
        self.reader.assert_not_called()
        self.fixture.windows.assert_not_called()

    def test_non_edp_internal_is_rejected(self):
        query = self.fixture.controller.api.query
        def lvds(flags):
            result = query(flags)
            result.paths[0].target.technology = 6
            return result
        self.fixture.controller.api.query = lvds
        with self.assertRaisesRegex(ValueError, 'eDP'):
            self.native.run(self.request)
        self.reader.assert_not_called()
        self.fixture.windows.assert_not_called()

    def test_sample_rejects_brightness_hdr_or_identity_change(self):
        self.fixture.windows.side_effect = [{'percent': 60}, {'percent': 61}]
        with self.assertRaisesRegex(ValueError, 'changed during factor'):
            self.native.run(self.request)
        self.fixture.windows.side_effect = None
        original = self.fixture.color.get
        self.fixture.color.get = Mock(side_effect=[original(None), {**original(None), 'hdrActive': False}])
        with self.assertRaisesRegex(ValueError, 'changed during factor'):
            self.native.run(self.request)
        self.fixture.color.get = original
        self.reader.side_effect = lambda *args: setattr(self.fixture.controller.api, 'device_path', lambda path: 'other') or {}
        with self.assertRaisesRegex(controls.InputIdentityError, 'identity changed'):
            self.native.run(self.request)

    def test_guarded_write_checks_hdr_before_write_and_after_confirmation(self):
        request = {'command': 'set_display_brightness', **self.fixture.target, 'percent': 70, 'expectedHdr': True}
        self.fixture.color.enabled = False
        with self.assertRaisesRegex(ValueError, 'no write was sent'):
            self.native.run(request)
        self.fixture.windows.assert_not_called()
        self.fixture.color.enabled = True
        original = self.fixture.windows.return_value
        def change_hdr(*args):
            self.fixture.color.enabled = False
            return original
        self.fixture.windows.side_effect = change_hdr
        with self.assertRaisesRegex(RuntimeError, 'HDR changed during brightness confirmation'):
            self.native.run(request)
        self.fixture.windows.assert_called_once_with('monitor-1', 70)

    def test_sample_rejects_source_reconfiguration_with_same_monitor_identity(self):
        query = self.fixture.controller.api.query
        def changed(flags):
            result = query(flags)
            result.paths[0].source.id += 1
            return result
        def sample(*args):
            self.fixture.controller.api.query = changed
            return {'factor': 1.01, 'rawMaxLuminance': 101, 'adjustedMaxLuminance': 100}
        self.reader.side_effect = sample
        with self.assertRaisesRegex(ValueError, 'changed during factor'):
            self.native.run(self.request)

    def test_worker_factor_envelope_keeps_trace(self):
        value = self.native.run(self.request)
        reply = Mock(returncode=0, stdout=json.dumps({'ok': True, 'result': value}).encode())
        with patch.object(controls.subprocess, 'run', return_value=reply):
            result = controls.control_request(self.request)
        self.assertEqual(result['brightnessPercent'], 60)
        self.assertEqual(result['controlTrace'][-1]['stage'], 'worker')


class FactorMetadataTests(unittest.TestCase):
    def test_com_method_dispatches_through_actual_ctypes_vtable(self):
        callback_type = C.WINFUNCTYPE(C.c_int32, C.c_void_p, C.c_uint32, C.POINTER(C.c_void_p))
        calls = []
        def enumerate_adapter(instance, index, output):
            calls.append(index)
            output[0] = C.c_void_p(99)
            return 0
        callback = callback_type(enumerate_adapter)
        table = (C.c_void_p * 14)()
        table[12] = C.cast(callback, C.c_void_p)
        interface = C.pointer(C.cast(table, C.POINTER(C.c_void_p)))
        output = C.c_void_p()
        self.assertEqual(factor.method(C.cast(interface, C.c_void_p), 12,
                         [C.c_uint32, C.POINTER(C.c_void_p)], 3, C.byref(output)), 0)
        self.assertEqual(calls, [3])
        self.assertEqual(output.value, 99)

    def test_powershell_winrt_projection_and_as_task_metadata_without_monitor_query(self):
        import base64
        import subprocess
        script = r'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$type = [Windows.Devices.Display.DisplayMonitor, Windows.Devices.Display, ContentType=WindowsRuntime]
$methods = @([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})
if ($methods.Count -ne 1) { throw 'A unique AsTask conversion was not found.' }
$null = $methods[0].MakeGenericMethod($type)
$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseInput([Console]::In.ReadToEnd(), [ref]$null, [ref]$errors)
if ($errors.Count) { throw 'Raw metadata script contains syntax errors.' }
'ok'
'''
        result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode('ascii')], input=factor.RAW_SCRIPT.encode(),
            capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertEqual(result.stdout.strip(), b'ok')

    def test_float32_formula_and_invalid_metadata(self):
        fixture = fixtures.ControlsTests()
        fixture.setUp()
        path = fixture.controller.query(2).paths[0]
        for raw, adjusted in ((101, 100), (1.0102251768112183, 1), (1000, 800)):
            with patch.object(factor, 'raw_luminance', return_value=raw), patch.object(factor, 'dxgi_luminance', return_value=adjusted):
                result = factor.read_factor(fixture.controller.api, path, 'monitor-1')
                self.assertEqual(result['factor'], C.c_float(C.c_float(raw).value / C.c_float(adjusted).value).value)
        for invalid in (0, -1, float('nan'), float('inf'), True, None, 1e-300, 1e300):
            with self.subTest(invalid=invalid), patch.object(factor, 'raw_luminance', return_value=100), \
                    patch.object(factor, 'dxgi_luminance', return_value=invalid), self.assertRaises(ValueError):
                factor.read_factor(fixture.controller.api, path, 'monitor-1')

    def test_dxgi_always_creates_factory_matches_luid_and_name_and_releases(self):
        def create(iid, output):
            output._obj.value = 1
            return 0
        dll = Mock()
        dll.CreateDXGIFactory1.side_effect = create
        released = []
        def invoke(pointer, index, arguments, *values):
            number = pointer.value
            if index == 2:
                released.append(number)
                return 0
            if number == 1 and index == 12:
                if values[0] > 0:
                    return C.c_int32(0x887a0002).value
                values[1]._obj.value = 2
            elif number == 2 and index == 10:
                values[0]._obj.luid.high, values[0]._obj.luid.low = 0, 99
            elif number == 2 and index == 7:
                if values[0] > 0:
                    return C.c_int32(0x887a0002).value
                values[1]._obj.value = 3
            elif number == 3 and index == 0:
                values[1]._obj.value = 4
            else:
                values[0]._obj.device = r'\\.\DISPLAY1'
                values[0]._obj.attached = True
                values[0]._obj.colorSpace = 12
                values[0]._obj.maximum = 500
            return 0
        with patch.object(factor.C, 'WinDLL', return_value=dll), patch.object(factor, 'method', side_effect=invoke):
            for _ in range(2):
                self.assertEqual(factor.dxgi_luminance((0, 99), r'\\.\display1'), 500)
            with self.assertRaisesRegex(ValueError, 'unique fresh DXGI'):
                factor.dxgi_luminance((0, 98), r'\\.\DISPLAY1')
        self.assertEqual(dll.CreateDXGIFactory1.call_count, 3)
        self.assertEqual(released.count(1), 3)
        self.assertEqual(released.count(4), 2)
        self.assertEqual(C.sizeof(factor.OutputDesc), 152)
        self.assertEqual(C.sizeof(factor.AdapterDesc), 312)

    def test_raw_worker_is_bounded_and_rejects_failure(self):
        reply = Mock(returncode=0, stdout=b'{"rawMaxLuminance":500}')
        with patch.object(factor.subprocess, 'run', return_value=reply) as worker:
            self.assertEqual(factor.raw_luminance('monitor'), 500)
            self.assertEqual(worker.call_args.kwargs['timeout'], 4)
            self.assertEqual(json.loads(worker.call_args.kwargs['input'])['identity'], 'monitor')
            reply.stdout = b'{"error":"unavailable"}'
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                factor.raw_luminance('monitor')


class FactorServiceTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ServiceTests()
        fixture.setUp()
        self.service, self.runner = fixture.service, fixture.runner
        self.request = {'version': 1, 'id': 'factor', 'command': 'get_brightness_factor',
                        'targetKey': 'target', 'monitorDevicePath': 'path'}

    def test_identity_is_mandatory_and_guard_flag_only_accepts_true(self):
        for field in ('targetKey', 'monitorDevicePath'):
            request = dict(self.request)
            request.pop(field)
            with self.assertRaises(ValueError):
                self.service.dispatch(request)
        for value in (False, 1, 'true'):
            with self.assertRaises(ValueError):
                self.service.dispatch({'version': 1, 'id': 'write', 'command': 'set_display_brightness',
                    'targetKey': 'target', 'monitorDevicePath': 'path', 'allowInterrupt': True, 'percent': 50, 'expectedHdr': value})
        self.runner.assert_not_called()

    def test_factor_is_readonly_uncached_and_busy_protected(self):
        self.service.dispatch(self.request)
        self.service.dispatch(self.request)
        self.assertEqual(self.runner.call_count, 2)
        self.assertEqual(self.service.seen, set())
        self.assertEqual(self.service.replies, {})
        self.service.running = True
        with self.assertRaisesRegex(ValueError, 'operation is running'):
            self.service.dispatch(self.request)

    def test_http_has_factor_envelope_and_readonly_error_classification(self):
        self.runner.return_value = {'factor': 1.01, 'brightnessPercent': 60}
        instance = server.create_server('127.0.0.1', 0, 123)
        instance.display_ports = self.service
        worker = threading.Thread(target=instance.serve_forever, kwargs={'poll_interval': .01})
        worker.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', instance.server_port, timeout=2)
            connection.request('POST', '/api', json.dumps(self.request), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            result = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(result['brightnessFactor']['factor'], 1.01)
            self.assertNotIn('get_brightness_factor', server.MUTATION_COMMANDS)
            connection.close()
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(2)
