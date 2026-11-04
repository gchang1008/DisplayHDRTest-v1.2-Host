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
    def test_query_only_uses_vcp_hint_after_fresh_endpoint_identity_match(self):
        for hint, use in ((dict(self.target), True), ({**self.target, 'monitorDevicePath': 'other'}, False)):
            with self.subTest(hint=hint):
                self.native_ddc.transfer.reset_mock()
                self.native.run({**self.request, '_brightnessVcp': hint})
                args = (r'\\.\DISPLAY1', None, True) if use else (r'\\.\DISPLAY1', None)
                self.native_ddc.transfer.assert_called_once_with(*args)

    def test_only_known_vcp_read_format_errors_mark_readonly_method_hint_transient(self):
        for code in (0xc0262589, 0xc026258a, 5):
            with self.subTest(code=code):
                self.native_ddc.transfer.side_effect = C.WinError(C.c_int32(code).value)
                result = self.native.run({**self.request, '_brightnessVcp': dict(self.target)})
                brightness = result['brightness']
                self.assertFalse(brightness['writable'])
                self.assertFalse(brightness['supported'])
                self.assertIsNone(brightness['current'])
                self.assertEqual(brightness.get('_vcpReadTransient', False), code in (0xc0262589, 0xc026258a))
        self.native_ddc.transfer.reset_mock()
        with self.assertRaises(OSError):
            self.native.run({'command': 'set_display_brightness', **self.target, 'percent': 60,
                             '_brightnessVcp': dict(self.target)})
        self.native_ddc.transfer.assert_called_once()

    def test_control_trace_times_endpoint_hdr_and_windows_and_survives_read_error(self):
        self.internal()
        result = self.native.run(self.request)
        self.assertTrue({'endpoint', 'hdr', 'windows-brightness'} <= {row['stage'] for row in result['controlTrace']})
        self.assertTrue(all(row['elapsedMs'] >= 0 for row in result['controlTrace']))
        self.assertGreaterEqual(result['controlElapsedMs'], 0)
        self.assertEqual(result['brightness']['ddcMethod'], 'windows')
        self.windows.side_effect = RuntimeError('WMI unavailable')
        result = self.native.run(self.request)
        self.assertTrue(any(row['stage'] == 'windows-brightness' and row['result'] == 'error'
                            and row['reason'] == 'WMI unavailable' for row in result['controlTrace']))

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
        self.assertLessEqual(len(self.native.trace), 63)

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
    def test_confirmed_vcp_route_skips_slow_capability_but_reads_and_confirms_again(self):
        ddc, api, values = self.make_vcp()
        clock = [0]
        original = api.GetMonitorCapabilities.side_effect
        def slow_caps(*args):
            clock[0] += 3
            return original(*args)
        api.GetMonitorCapabilities.side_effect = slow_caps
        with patch.object(controls.time, 'perf_counter', side_effect=lambda: clock[0]):
            first = ddc.transfer(r'\\.\DISPLAY1')
            second = ddc.transfer(r'\\.\DISPLAY1', 75, prefer_vcp=True)
        self.assertEqual(first['ddcMethod'], 'vcp')
        self.assertEqual(second['percent'], 75)
        api.GetMonitorCapabilities.assert_called_once()
        self.assertEqual(api.GetVCPFeatureAndVCPFeatureReply.call_count, 3)
        api.SetVCPFeature.assert_called_once()
        self.assertEqual([row['elapsedMs'] for row in ddc.trace if row['stage'] == 'capability'], [3000, 0])
        self.assertEqual(ddc.trace[-1]['stage'], 'confirm')

    def test_hint_read_failure_does_not_try_high_level_or_write(self):
        ddc, api, values = self.make_vcp()
        api.GetVCPFeatureAndVCPFeatureReply.return_value = 0
        api.GetVCPFeatureAndVCPFeatureReply.side_effect = None
        with self.assertRaises(OSError):
            ddc.transfer(r'\\.\DISPLAY1', 60, prefer_vcp=True)
        api.GetMonitorCapabilities.assert_not_called()
        api.GetMonitorBrightness.assert_not_called()
        api.SetVCPFeature.assert_not_called()
        api.SetMonitorBrightness.assert_not_called()
        self.assertEqual(ddc.trace[-1]['result'], 'error')

    def make_vcp(self, confirm=True, error=0xc0262587):
        ddc, api = self.make()
        def caps(*args):
            C.set_last_error(C.c_int32(error).value)
            return 0
        api.GetMonitorCapabilities.side_effect = caps
        values = [100, 200, 1]
        def read(handle, code, kind, current, maximum):
            kind._obj.value, current._obj.value, maximum._obj.value = values[2], values[0], values[1]
            return 1
        def write(handle, code, value):
            if confirm:
                values[0] = value
            return 1
        api.GetVCPFeatureAndVCPFeatureReply.side_effect = read
        api.SetVCPFeature.side_effect = write
        return ddc, api, values

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

    def test_invalid_capabilities_string_reads_vcp_without_writing(self):
        ddc, api, _ = self.make_vcp()
        result = ddc.transfer(r'\\.\DISPLAY1')
        self.assertEqual((result['minimum'], result['current'], result['maximum'], result['percent']), (0, 100, 200, 50))
        self.assertEqual(api.GetVCPFeatureAndVCPFeatureReply.call_args.args[:2], (3, 0x10))
        api.GetMonitorBrightness.assert_not_called()
        api.SetVCPFeature.assert_not_called()
        api.SetMonitorBrightness.assert_not_called()
        api.DestroyPhysicalMonitors.assert_called_once()

    def test_invalid_command_field_can_read_valid_brightness_vcp_without_writing(self):
        ddc, api, _ = self.make_vcp(error=0xc0262589)
        result = ddc.transfer(r'\\.\DISPLAY1')
        self.assertEqual(result['percent'], 50)
        self.assertEqual(result['ddcMethod'], 'vcp')
        api.GetVCPFeatureAndVCPFeatureReply.assert_called_once()
        api.SetVCPFeature.assert_not_called()
        api.SetMonitorBrightness.assert_not_called()

    def test_invalid_command_field_fallback_failure_or_invalid_data_never_writes(self):
        for outcome in ('read-error', 'invalid-type', 'invalid-range'):
            ddc, api, state = self.make_vcp(error=0xc0262589)
            if outcome == 'read-error':
                api.GetVCPFeatureAndVCPFeatureReply.side_effect = OSError('VCP unavailable')
            elif outcome == 'invalid-type':
                state[2] = 0
            else:
                state[1] = 0
            with self.subTest(outcome=outcome), self.assertRaises((OSError, ValueError)):
                ddc.transfer(r'\\.\DISPLAY1', 70)
            api.SetVCPFeature.assert_not_called()
            api.SetMonitorBrightness.assert_not_called()
            api.DestroyPhysicalMonitors.assert_called_once()

    def test_invalid_command_field_during_high_level_read_or_write_does_not_add_fallback(self):
        for operation in ('read', 'write'):
            ddc, api = self.make()
            error = C.WinError(C.c_int32(0xc0262589).value)
            if operation == 'read':
                api.GetMonitorBrightness.side_effect = error
            else:
                api.SetMonitorBrightness.side_effect = error
            with self.subTest(operation=operation), self.assertRaises(OSError):
                ddc.transfer(r'\\.\DISPLAY1', 70)
            self.assertEqual(api.SetMonitorBrightness.call_count, int(operation == 'write'))
            api.GetVCPFeatureAndVCPFeatureReply.assert_not_called()
            api.SetVCPFeature.assert_not_called()

    def test_vcp_write_is_once_and_confirmed_using_same_method(self):
        ddc, api, _ = self.make_vcp()
        result = ddc.transfer(r'\\.\DISPLAY1', 70)
        self.assertEqual((result['current'], result['percent'], result['changed']), (140, 70, True))
        api.SetVCPFeature.assert_called_once_with(3, 0x10, 140)
        self.assertEqual(api.GetVCPFeatureAndVCPFeatureReply.call_count, 2)
        api.SetMonitorBrightness.assert_not_called()
        api.DestroyPhysicalMonitors.assert_called_once()

    def test_vcp_same_value_skips_write_and_invalid_reply_never_writes(self):
        ddc, api, _ = self.make_vcp()
        self.assertFalse(ddc.transfer(r'\\.\DISPLAY1', 50)['changed'])
        api.SetVCPFeature.assert_not_called()
        for values in ((100, 0, 1), (201, 200, 1), (100, 200, 0)):
            ddc, api, state = self.make_vcp()
            state[:] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                ddc.transfer(r'\\.\DISPLAY1', 70)
            api.SetVCPFeature.assert_not_called()
            api.DestroyPhysicalMonitors.assert_called_once()

    def test_unconfirmed_or_failed_vcp_write_never_retries(self):
        for fails in (False, True):
            ddc, api, _ = self.make_vcp(confirm=False)
            if fails:
                api.SetVCPFeature.side_effect = OSError('Write failed')
            with self.subTest(fails=fails), self.assertRaises((OSError, RuntimeError)):
                ddc.transfer(r'\\.\DISPLAY1', 70)
            api.SetVCPFeature.assert_called_once()
            api.SetMonitorBrightness.assert_not_called()
            api.DestroyPhysicalMonitors.assert_called_once()

    def test_other_capability_errors_do_not_fallback(self):
        ddc, api, _ = self.make_vcp(error=5)
        with self.assertRaises(OSError):
            ddc.transfer(r'\\.\DISPLAY1', 70)
        api.GetVCPFeatureAndVCPFeatureReply.assert_not_called()
        api.SetVCPFeature.assert_not_called()

    def test_mccs_declaration_errors_read_vcp_for_different_brightness_ranges(self):
        for code in (0xc02625d9, 0xc02625da, 0xc02625db, 0xc02625dc, 0xc026258a):
            for current, maximum in ((21, 100), (100, 200), (1000, 65535)):
                with self.subTest(code=hex(code), maximum=maximum):
                    ddc, api, state = self.make_vcp(error=code)
                    state[:2] = current, maximum
                    result = ddc.transfer(r'\\.\DISPLAY1')
                    self.assertEqual(result['current'], current)
                    self.assertEqual(result['maximum'], maximum)
                    self.assertEqual(result['percent'], round(current * 100 / maximum))
                    self.assertEqual(result['ddcMethod'], 'vcp')
                    api.GetVCPFeatureAndVCPFeatureReply.assert_called_once()
                    api.SetVCPFeature.assert_not_called()
                    api.SetMonitorBrightness.assert_not_called()

    def test_missing_high_level_brightness_flag_probes_vcp_but_never_replays_failed_read(self):
        for fails in (False, True):
            ddc, api, _ = self.make_vcp()
            api.GetMonitorCapabilities.side_effect = lambda *args: 1
            if fails:
                api.GetVCPFeatureAndVCPFeatureReply.side_effect = C.WinError(C.c_int32(0xc0262587).value)
            with self.subTest(fails=fails):
                if fails:
                    with self.assertRaises(OSError):
                        ddc.transfer(r'\\.\DISPLAY1', 70)
                else:
                    self.assertEqual(ddc.transfer(r'\\.\DISPLAY1')['percent'], 50)
                api.GetVCPFeatureAndVCPFeatureReply.assert_called_once()
                api.GetMonitorBrightness.assert_not_called()
                api.SetVCPFeature.assert_not_called()
                api.SetMonitorBrightness.assert_not_called()

    def test_mccs_fallback_rejects_unavailable_invalid_type_and_range_without_writing(self):
        for state_values in (None, (21, 100, 0), (101, 100, 1), (0, 0, 1)):
            ddc, api, state = self.make_vcp(error=0xc02625dc)
            if state_values is None:
                api.GetVCPFeatureAndVCPFeatureReply.side_effect = OSError('DDC/CI not responding')
            else:
                state[:] = state_values
            with self.subTest(values=state_values), self.assertRaises((OSError, ValueError)):
                ddc.transfer(r'\\.\DISPLAY1', 70)
            api.GetVCPFeatureAndVCPFeatureReply.assert_called_once()
            api.SetVCPFeature.assert_not_called()
            api.SetMonitorBrightness.assert_not_called()

    def test_mccs_initial_read_can_fallback_but_failed_writes_cannot(self):
        ddc, api, _ = self.make_vcp()
        api.GetMonitorCapabilities.side_effect = lambda handle, caps, temperatures: setattr(caps._obj, 'value', 2) or 1
        api.GetMonitorBrightness.side_effect = C.WinError(C.c_int32(0xc02625dc).value)
        self.assertEqual(ddc.transfer(r'\\.\DISPLAY1')['ddcMethod'], 'vcp')
        api.SetVCPFeature.assert_not_called()
        ddc, api = self.make()
        api.SetMonitorBrightness.side_effect = C.WinError(C.c_int32(0xc02625dc).value)
        with self.assertRaises(OSError):
            ddc.transfer(r'\\.\DISPLAY1', 70)
        api.SetMonitorBrightness.assert_called_once()
        api.GetVCPFeatureAndVCPFeatureReply.assert_not_called()
        api.SetVCPFeature.assert_not_called()

    def test_high_level_write_failure_does_not_start_vcp_fallback(self):
        ddc, api = self.make()
        api.SetMonitorBrightness.side_effect = C.WinError(C.c_int32(0xc0262587).value)
        with self.assertRaises(OSError):
            ddc.transfer(r'\\.\DISPLAY1', 70)
        api.SetMonitorBrightness.assert_called_once()
        api.GetVCPFeatureAndVCPFeatureReply.assert_not_called()
        api.SetVCPFeature.assert_not_called()
        api.DestroyPhysicalMonitors.assert_called_once()

    def test_vcp_read_failure_or_changed_range_does_not_claim_success(self):
        ddc, api, _ = self.make_vcp()
        api.GetVCPFeatureAndVCPFeatureReply.side_effect = OSError('VCP unavailable')
        with self.assertRaises(OSError):
            ddc.transfer(r'\\.\DISPLAY1', 70)
        api.SetVCPFeature.assert_not_called()
        ddc, api, state = self.make_vcp()
        def write(handle, code, value):
            state[:2] = value, 250
            return 1
        api.SetVCPFeature.side_effect = write
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            ddc.transfer(r'\\.\DISPLAY1', 70)
        api.SetVCPFeature.assert_called_once()
        api.DestroyPhysicalMonitors.assert_called_once()

    def test_malformed_capabilities_at_initial_brightness_read_can_fallback(self):
        ddc, api, _ = self.make_vcp()
        api.GetMonitorCapabilities.side_effect = lambda handle, caps, temperature: setattr(caps._obj, 'value', 2) or 1
        api.GetMonitorBrightness.side_effect = C.WinError(C.c_int32(0xc0262587).value)
        self.assertEqual(ddc.transfer(r'\\.\DISPLAY1')['percent'], 50)
        api.SetVCPFeature.assert_not_called()


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
    def vcp_result(self, target='target', path='path'):
        return {'target': {'targetKey': target, 'monitorDevicePath': path, 'internal': False},
                'hdr': {'enabled': False}, 'brightness': {'writable': True, 'ddcMethod': 'vcp'}}

    def brightness_request(self, identifier='write', target='target', path='path'):
        return {'version': 1, 'id': identifier, 'command': 'set_display_brightness', 'targetKey': target,
                'monitorDevicePath': path, 'allowInterrupt': True, 'percent': 60}

    def test_vcp_hint_is_host_private_identity_scoped_and_refresh_reads_known_method(self):
        snapshot = self.vcp_result()
        self.runner.return_value = snapshot
        self.service.dispatch(self.request)
        self.runner.return_value = {'displayControls': snapshot}
        request = self.brightness_request()
        self.service.dispatch(request)
        self.assertTrue(self.runner.call_args.args[0]['_brightnessVcp'])
        self.assertNotIn('_brightnessVcp', request)
        self.service.dispatch(request)
        self.assertEqual(self.runner.call_count, 2)
        self.service.dispatch(self.brightness_request('other', path='new-path'))
        self.assertNotIn('_brightnessVcp', self.runner.call_args.args[0])
        self.runner.return_value = snapshot
        self.service.dispatch({**self.request, 'id': 'refresh'})
        self.assertEqual(self.runner.call_args.args[0]['_brightnessVcp'], {'targetKey': 'target', 'monitorDevicePath': 'path'})
        with self.assertRaises(ValueError):
            self.service.dispatch({**self.brightness_request('private'), '_brightnessVcp': True})

    def test_failed_write_clears_but_successful_hdr_off_preserves_vcp_hint_without_replay(self):
        snapshot = self.vcp_result()
        self.runner.return_value = snapshot
        self.service.dispatch(self.request)
        self.runner.side_effect = RuntimeError('write unconfirmed')
        with self.assertRaises(RuntimeError):
            self.service.dispatch(self.brightness_request())
        self.assertIsNone(self.service.brightness_vcp_target)
        self.assertEqual(self.runner.call_count, 2)
        self.runner.side_effect = None
        self.runner.return_value = snapshot
        self.service.dispatch({**self.request, 'id': 'refresh'})
        self.runner.return_value = {'displayControls': snapshot}
        self.service.dispatch({'version': 1, 'id': 'hdr', 'command': 'set_display_hdr', 'targetKey': 'target',
                               'monitorDevicePath': 'path', 'allowInterrupt': True, 'enabled': False})
        self.assertEqual(self.service.brightness_vcp_target, ('target', 'path'))

    def test_hdr_on_and_off_and_refresh_keep_only_same_device_method_hint(self):
        self.service.brightness_vcp_target = ('target', 'path')
        on = self.vcp_result()
        on['hdr']['enabled'] = True
        on['brightness'] = {'supported': False, 'writable': False, 'current': None}
        self.runner.return_value = {'displayControls': on}
        request = {'version': 1, 'id': 'on', 'command': 'set_display_hdr', 'targetKey': 'target',
                   'monitorDevicePath': 'path', 'allowInterrupt': True, 'enabled': True}
        self.service.dispatch(request)
        self.assertEqual(self.service.brightness_vcp_target, ('target', 'path'))
        self.assertEqual(self.runner.call_args.args[0]['_brightnessVcp'], {'targetKey': 'target', 'monitorDevicePath': 'path'})
        self.runner.return_value = {'displayControls': self.vcp_result()}
        self.service.dispatch({**request, 'id': 'off', 'enabled': False})
        self.assertEqual(self.service.brightness_vcp_target, ('target', 'path'))
        self.runner.return_value = self.vcp_result()
        self.service.dispatch({**self.request, 'id': 'refresh'})
        self.assertIn('_brightnessVcp', self.runner.call_args.args[0])
        self.assertEqual(self.service.brightness_vcp_target, ('target', 'path'))

    def test_transient_read_retains_method_without_exposing_private_marker_or_writable(self):
        self.service.brightness_vcp_target = ('target', 'path')
        result = self.vcp_result()
        result['brightness'] = {'supported': False, 'writable': False, 'current': None, '_vcpReadTransient': True}
        self.runner.return_value = result
        response = self.service.dispatch(self.request)
        self.assertEqual(self.service.brightness_vcp_target, ('target', 'path'))
        self.assertNotIn('_vcpReadTransient', response['brightness'])
        self.assertFalse(response['brightness']['writable'])
        self.assertIsNone(response['brightness']['current'])

    def test_unknown_hdr_hard_read_failure_and_new_device_clear_old_method_hint(self):
        for kind in ('unknown-hdr', 'read-failure', 'new-device'):
            with self.subTest(kind=kind):
                self.service.brightness_vcp_target = ('target', 'path')
                result = self.vcp_result()
                result['brightness'] = {'supported': False, 'writable': False, 'current': None}
                if kind == 'unknown-hdr':
                    result['hdr']['enabled'] = None
                if kind == 'new-device':
                    result['target']['monitorDevicePath'] = 'new-path'
                    result['brightness']['_vcpReadTransient'] = True
                self.runner.return_value = result
                self.service.dispatch({**self.request, 'id': kind})
                self.assertIsNone(self.service.brightness_vcp_target)

    def test_input_mutation_clears_vcp_hint_even_when_operation_fails(self):
        self.service.brightness_vcp_target = ('target', 'path')
        with self.assertRaises(ValueError):
            self.service.dispatch({'version': 1, 'id': 'input', 'command': 'write_display_input',
                'targetKey': 'target', 'monitorDevicePath': 'path', 'allowInterrupt': True, 'value': 18})
        self.assertIsNone(self.service.brightness_vcp_target)

    def test_worker_failure_keeps_trace_and_total_elapsed(self):
        trace = [{'stage': 'confirm', 'result': 'error', 'elapsedMs': 12, 'reason': 'not confirmed'}]
        reply = Mock(returncode=0, stdout=json.dumps({'ok': False, 'error': 'not confirmed', 'controlTrace': trace}).encode())
        with patch.object(controls.subprocess, 'run', return_value=reply), self.assertRaises(controls.ControlError) as raised:
            controls.control_request({'command': 'set_display_brightness'})
        self.assertEqual(raised.exception.controlTrace[:-1], trace)
        self.assertEqual(raised.exception.controlTrace[-1]['stage'], 'worker')
        self.assertGreaterEqual(raised.exception.controlElapsedMs, 0)

    def test_http_mutation_error_preserves_timing_and_uncertain_outcome(self):
        trace = [{'stage': 'write', 'result': 'error', 'elapsedMs': 3000, 'reason': 'DDC failed'}]
        self.runner.side_effect = controls.ControlError('DDC failed', trace, 3100)
        instance = server.create_server('127.0.0.1', 0, 123)
        instance.display_ports = self.service
        worker = threading.Thread(target=instance.serve_forever, kwargs={'poll_interval': .01})
        worker.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', instance.server_port, timeout=2)
            connection.request('POST', '/api', json.dumps(self.brightness_request()), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            result = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 409)
            self.assertTrue(result['error']['requestMayHaveApplied'])
            self.assertEqual(result['error']['controlTrace'], trace)
            self.assertEqual(result['error']['controlElapsedMs'], 3100)
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(2)

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
