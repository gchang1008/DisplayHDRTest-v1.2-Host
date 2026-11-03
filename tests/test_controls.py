"""Other controls use simulated Windows and monitor interfaces only."""
import ctypes as C
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import displayhdr_controls as controls
import displayhdr_ports as ports
import displayhdr_server as server
from displayhdr_display_paths import Header, TargetName
from displayhdr_monitor_input import SourceName, MonitorInfo, PhysicalMonitor
from displayhdr_hdr_control import ColorState, WindowsColorApi
from test_display_ports import Controller, Renderer


class Color:
    def __init__(self):
        self.enabled = False
        self.legacy = False
        self.confirm = True
        self.writes = []

    def get(self, path):
        return {'supported': True, 'enabled': self.enabled, 'limitedByPolicy': False,
                'legacyAdvancedColor': self.legacy, 'hdrActive': None if self.legacy else self.enabled}

    def set(self, path, state, enabled):
        self.writes.append(enabled)
        if self.confirm:
            self.enabled = enabled


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller()
        self.controller.api.dll.DisplayConfigGetDeviceInfo = self.name
        self.color = Color()
        self.native_ddc = Mock()
        self.native_ddc.transfer.return_value = {'minimum': 10, 'maximum': 210, 'current': 110,
                                               'percent': 50, 'levels': [], 'changed': False}
        self.windows = Mock(return_value={'minimum': 0, 'maximum': 100, 'current': 60,
                                         'percent': 60, 'levels': [0, 20, 40, 60, 80, 100], 'changed': False})
        self.clock = 0
        self.native = controls.NativeControls(self.controller.api, self.color, self.native_ddc,
            self.windows, clock=lambda: self.clock, sleep=self.sleep)
        self.request = {'command': 'get_display_controls'}
        self.target = {'targetKey': '00000000:00000063/1', 'monitorDevicePath': 'monitor-1'}

    def sleep(self, duration):
        self.clock += duration

    def name(self, packet):
        header = C.cast(packet, C.POINTER(Header)).contents
        if header.type == 1:
            C.cast(packet, C.POINTER(SourceName)).contents.device = r'\\.\DISPLAY1'
        else:
            self.controller.name(packet)
        return 0

    def internal(self):
        query = self.controller.query
        def get(flags):
            result = query(flags)
            result.paths[0].target.technology = 11
            return result
        self.controller.api.query = get

    def test_unpaired_external_query_reads_brightness_without_source_or_renderer_actions(self):
        result = self.native.run(self.request)
        self.assertFalse(result['target']['internal'])
        self.assertEqual(result['brightness']['percent'], 50)
        self.assertEqual(result['brightness']['method'], 'ddc')
        self.assertTrue(result['brightness']['writable'])
        self.windows.assert_not_called()
        self.assertFalse(self.color.writes)
        self.assertFalse(self.controller.trials)

    def test_internal_uses_only_windows_brightness_even_with_hdr_on(self):
        self.internal()
        self.color.enabled = True
        result = self.native.run(self.request)
        self.assertEqual(result['target']['connection'], 'eDP')
        self.assertTrue(result['target']['internal'])
        self.assertEqual(result['brightness']['method'], 'windows')
        self.assertEqual(result['brightness']['levels'], [0, 20, 40, 60, 80, 100])
        self.native_ddc.transfer.assert_not_called()

    def test_external_hdr_on_or_unknown_never_reads_or_writes_ddc(self):
        for enabled, legacy in ((True, False), (False, True)):
            self.color.enabled, self.color.legacy = enabled, legacy
            result = self.native.run(self.request)
            self.assertFalse(result['brightness']['writable'])
            self.assertIsNone(result['brightness']['current'])
            with self.assertRaisesRegex(ValueError, 'HDR'):
                self.native.run({'command': 'set_display_brightness', **self.target, 'percent': 40})
        self.native_ddc.transfer.assert_not_called()

    def test_multiple_or_wrong_active_endpoint_reject_before_control(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.native.run({'command': 'set_display_hdr', **self.target, 'monitorDevicePath': 'other', 'enabled': True})
        query = self.controller.api.query
        self.controller.api.query = lambda flags: query(1)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.native.run(self.request)
        self.native_ddc.transfer.assert_not_called()
        self.assertFalse(self.color.writes)

    def test_hdr_on_off_readback_and_same_state_noop(self):
        for enabled, changed in ((True, True), (True, False), (False, True)):
            result = self.native.run({'command': 'set_display_hdr', **self.target, 'enabled': enabled})
            self.assertEqual(result['changed'], changed)
            self.assertIs(result['displayControls']['hdr']['enabled'], enabled)
        self.assertEqual(self.color.writes, [True, False])

    def test_hdr_unconfirmed_raises_after_single_write(self):
        self.color.confirm = False
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            self.native.run({'command': 'set_display_hdr', **self.target, 'enabled': True})
        self.assertEqual(self.color.writes, [True])
        self.assertGreaterEqual(self.clock, 5)

    def test_query_brightness_failure_is_unavailable_but_mutation_failure_is_error(self):
        self.native_ddc.transfer.side_effect = OSError('DDC unavailable')
        result = self.native.run(self.request)
        self.assertFalse(result['brightness']['supported'])
        self.assertIn('DDC unavailable', result['brightness']['error'])
        with self.assertRaises(OSError):
            self.native.run({'command': 'set_display_brightness', **self.target, 'percent': 70})

    def test_brightness_write_uses_percent_and_returns_confirmed_value(self):
        self.native_ddc.transfer.return_value.update(current=150, percent=70, changed=True)
        result = self.native.run({'command': 'set_display_brightness', **self.target, 'percent': 70})
        self.native_ddc.transfer.assert_called_once_with(r'\\.\DISPLAY1', 70)
        self.assertTrue(result['changed'])
        self.assertEqual(result['displayControls']['brightness']['percent'], 70)

    def test_identity_change_during_write_is_not_reported_as_success(self):
        def changed(*args):
            self.controller.current = 2
            return {'minimum': 0, 'maximum': 100, 'current': 70, 'percent': 70, 'levels': [], 'changed': True}
        self.native_ddc.transfer.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.native.run({'command': 'set_display_brightness', **self.target, 'percent': 70})

    def test_hdr_change_during_brightness_query_disables_write_in_final_snapshot(self):
        def changed(*args):
            self.color.enabled = True
            return {'minimum': 0, 'maximum': 100, 'current': 70, 'percent': 70, 'levels': [], 'changed': False}
        self.native_ddc.transfer.side_effect = changed
        result = self.native.run(self.request)
        self.assertTrue(result['hdr']['enabled'])
        self.assertFalse(result['brightness']['writable'])
        self.assertIsNone(result['brightness']['current'])

    def test_hdr_change_during_brightness_write_is_unconfirmed_without_replay(self):
        def changed(*args):
            self.color.enabled = True
            return {'minimum': 0, 'maximum': 100, 'current': 70, 'percent': 70, 'levels': [], 'changed': True}
        self.native_ddc.transfer.side_effect = changed
        with self.assertRaisesRegex(RuntimeError, 'unconfirmed'):
            self.native.run({'command': 'set_display_brightness', **self.target, 'percent': 70})
        self.native_ddc.transfer.assert_called_once()

    def test_fixed_worker_timeout_and_windows_level_validation(self):
        with patch.object(controls.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 10)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                controls.control_request({'command': 'get_display_controls'})
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
        identity = r'\\?\DISPLAY#MODEL#INSTANCE#{guid}'
        reply = Mock(returncode=0, stdout=json.dumps({'minimum': 0, 'maximum': 100,
            'current': 60, 'levels': [0, 20, 40, 60, 80, 100], 'changed': False}).encode())
        with patch.object(controls.subprocess, 'run', return_value=reply) as run:
            self.assertEqual(controls.windows_brightness(identity)['percent'], 60)
            self.assertEqual(run.call_args.kwargs['timeout'], 4)
            reply.stdout = b'{"current": 200, "minimum":0, "maximum":100, "levels":[0,100]}'
            with self.assertRaises(ValueError):
                controls.windows_brightness(identity)


class DdcTests(unittest.TestCase):
    def make(self, confirm=True):
        user, dxva = Mock(), Mock()
        user.EnumDisplayMonitors.side_effect = lambda dc, rect, callback, data: callback(1, None, None, 0)
        def info(handle, value):
            C.cast(value, C.POINTER(MonitorInfo)).contents.device = r'\\.\DISPLAY1'
            return 1
        user.GetMonitorInfoW.side_effect = info
        def count(handle, value):
            value._obj.value = 1
            return 1
        dxva.GetNumberOfPhysicalMonitorsFromHMONITOR.side_effect = count
        def physical(handle, count, value):
            value[0].handle = 3
            return 1
        dxva.GetPhysicalMonitorsFromHMONITOR.side_effect = physical
        def caps(handle, value, temperatures):
            value._obj.value = 2
            return 1
        dxva.GetMonitorCapabilities.side_effect = caps
        current = [110]
        def read(handle, low, value, high):
            low._obj.value, value._obj.value, high._obj.value = 10, current[0], 210
            return 1
        dxva.GetMonitorBrightness.side_effect = read
        def write(handle, value):
            if confirm:
                current[0] = value
            return 1
        dxva.SetMonitorBrightness.side_effect = write
        dxva.DestroyPhysicalMonitors.return_value = 1
        return controls.WindowsBrightness(user, dxva), dxva

    def test_native_percent_mapping_single_write_readback_and_cleanup(self):
        ddc, api = self.make()
        result = ddc.transfer(r'\\.\DISPLAY1', 70)
        api.SetMonitorBrightness.assert_called_once_with(3, 150)
        self.assertEqual(result['current'], 150)
        self.assertEqual(result['percent'], 70)
        api.DestroyPhysicalMonitors.assert_called_once()

    def test_native_unconfirmed_write_does_not_retry_and_always_releases(self):
        ddc, api = self.make(False)
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            ddc.transfer(r'\\.\DISPLAY1', 70)
        api.SetMonitorBrightness.assert_called_once()
        api.DestroyPhysicalMonitors.assert_called_once()


class HdrPacketTests(unittest.TestCase):
    def test_enable_and_disable_use_exact_modern_or_legacy_flag(self):
        api = WindowsColorApi.__new__(WindowsColorApi)
        api.dll = Mock()
        packets = []
        def record(packet):
            value = C.cast(packet, C.POINTER(ColorState)).contents
            packets.append((value.header.type, value.value))
            return 0
        api.dll.DisplayConfigSetDeviceInfo.side_effect = record
        path = Controller().query(2).paths[0]
        api.enable(path, {'legacyAdvancedColor': True})
        api.set(path, {'legacyAdvancedColor': False}, True)
        api.set(path, {'legacyAdvancedColor': False}, False)
        self.assertEqual(packets, [(10, 1), (16, 1), (16, 0)])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.runner = Mock(return_value={'target': {'targetKey': 'target', 'monitorDevicePath': 'path'}})
        self.service = ports.DisplayPortService(Renderer(), controls_runner=self.runner)
        self.request = {'version': 1, 'id': 'controls', 'command': 'get_display_controls'}

    def test_query_does_not_require_pairing_renderer_or_allowinterrupt(self):
        self.assertEqual(self.service.dispatch(self.request), self.runner.return_value)
        self.runner.assert_called_once_with(self.request)
        self.assertFalse(self.service.busy())

    def test_duplicate_success_is_cached_but_failed_request_is_never_replayed(self):
        self.service.dispatch(self.request)
        self.service.dispatch(self.request)
        self.runner.assert_called_once()
        self.runner.side_effect = TimeoutError('unknown result')
        self.request['id'] = 'failed'
        with self.assertRaises(TimeoutError):
            self.service.dispatch(self.request)
        self.assertFalse(self.service.busy())
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            self.service.dispatch(self.request)
        self.assertEqual(self.runner.call_count, 2)

    def test_validation_and_busy_reject_before_worker(self):
        for extra in ({'allowInterrupt': True}, {'targetKey': 'target'}, {'version': True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.service.dispatch({**self.request, **extra})
        request = {**self.request, 'command': 'set_display_brightness', 'targetKey': 'target',
                   'monitorDevicePath': 'path', 'allowInterrupt': True, 'percent': True}
        with self.assertRaises(ValueError):
            self.service.dispatch(request)
        request = {**request, 'command': 'set_display_hdr', 'enabled': 1}
        request.pop('percent')
        with self.assertRaises(ValueError):
            self.service.dispatch(request)
        self.service.running = True
        with self.assertRaises(ValueError):
            self.service.dispatch(self.request)
        self.runner.assert_not_called()

    def test_http_displaycontrols_envelope_and_readonly_classification(self):
        instance = server.create_server('127.0.0.1', 0, 123)
        instance.display_ports = self.service
        worker = threading.Thread(target=instance.serve_forever, kwargs={'poll_interval': .01})
        worker.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', instance.server_port, timeout=2)
            connection.request('POST', '/api', json.dumps(self.request), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            result = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertIn('displayControls', result)
            self.assertNotIn('get_display_controls', server.MUTATION_COMMANDS)
            self.assertIn('set_display_hdr', server.MUTATION_COMMANDS)
            self.assertIn('set_display_brightness', server.MUTATION_COMMANDS)
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
