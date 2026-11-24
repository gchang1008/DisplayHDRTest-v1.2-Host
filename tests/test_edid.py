"""EDID tests use synthetic blocks and isolated endpoints; no display access."""
import base64
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import displayhdr_edid as edid
import displayhdr_ports as ports
import displayhdr_server as server
from test_display_ports import Controller, Renderer, MultiController


IDENTITY = r'\\?\DISPLAY#DEL1234#4&1234&0&UID123#{00000000-0000-0000-0000-000000000000}'


def raw_edid(extensions):
    block = bytearray(128)
    block[:8] = bytes.fromhex('00ffffffffffff00')
    block[126] = extensions
    block[127] = -sum(block) % 256
    return bytes(block) + bytes(128 * extensions)


def output_for(data):
    return '\n'.join(json.dumps({'block': i // 128,
        'data': base64.b64encode(data[i:i + 128]).decode('ascii')})
        for i in range(0, len(data), 128)).encode()


def override_edid(extensions=2, base_extensions=1):
    data = bytearray(raw_edid(base_extensions)[:128] + bytes(128 * extensions))
    data[128:135] = bytes((2, 3, 7, 0, 0xe2, 0x78, extensions))
    data[255] = -sum(data[128:255]) % 256
    return bytes(data)


class EdidReaderTests(unittest.TestCase):
    def test_read_trace_includes_blocks_normal_stop_cache_skip_and_total_time(self):
        data = raw_edid(2)
        output = output_for(data) + b'\n' + json.dumps(
            {'end': 3, 'elapsedMs': 1.25, 'reason': 'No more EDID blocks.'}).encode()
        with patch.object(edid.subprocess, 'run', return_value=SimpleNamespace(stdout=output, returncode=0)):
            result = edid.read_edid(IDENTITY)
        trace = result['readTrace']
        self.assertEqual([event['result'] for event in trace], ['read', 'read', 'read', 'end', 'skipped'])
        self.assertEqual([event['block'] for event in trace[:4]], [0, 1, 2, 3])
        self.assertEqual(trace[3]['reason'], 'No more EDID blocks.')
        self.assertEqual(trace[3]['elapsedMs'], 1.25)
        self.assertEqual(trace[-1]['stage'], 'registry')
        self.assertGreaterEqual(result['readElapsedMs'], 0)
        self.assertEqual(result['warnings'], [])
        self.assertNotIn('dataBase64', json.dumps(trace))
        self.assertNotIn('data', {key for event in trace for key in event})

    def test_timeout_trace_retains_successful_blocks_and_stop_reason(self):
        data = raw_edid(2)[:256]
        timeout = subprocess.TimeoutExpired('powershell', 8, output=output_for(data))
        trace = []
        with patch.object(edid.subprocess, 'run', side_effect=timeout):
            actual, warnings = edid.wmi_edid(IDENTITY, trace)
        self.assertEqual(actual, data)
        self.assertEqual([event['result'] for event in trace], ['read', 'read', 'timeout'])
        self.assertEqual(trace[-1]['block'], 2)
        self.assertIn('8 seconds', trace[-1]['reason'])
        self.assertGreaterEqual(trace[-1]['elapsedMs'], 0)
        self.assertTrue(warnings)

    def test_registry_trace_records_use_empty_cache_and_failure(self):
        data = raw_edid(2)
        for cached, outcome in ((data, 'used'), (b'', 'skipped'), (OSError('cache failed'), 'error')):
            with self.subTest(outcome=outcome), \
                    patch.object(edid, 'wmi_edid', return_value=(b'', [])), \
                    patch.object(edid, 'registry_edid', **({'side_effect': cached} if isinstance(cached, Exception)
                                                        else {'return_value': cached})):
                result = edid.read_edid(IDENTITY)
            event = result['readTrace'][-1]
            self.assertEqual(event['stage'], 'registry')
            self.assertEqual(event['result'], outcome)
            self.assertTrue(event['reason'])
            self.assertGreaterEqual(event['elapsedMs'], 0)

    def test_wmi_start_failure_is_recorded_before_registry_fallback(self):
        with patch.object(edid, 'wmi_edid', side_effect=OSError('worker unavailable')), \
                patch.object(edid, 'registry_edid', side_effect=OSError('cache unavailable')):
            result = edid.read_edid(IDENTITY)
        self.assertEqual([(event['stage'], event['result']) for event in result['readTrace']],
                         [('wmi', 'error'), ('registry', 'error')])
        self.assertIn('worker unavailable', result['readTrace'][0]['reason'])

    def test_extra_blocks_are_preserved_and_not_replaced_by_registry(self):
        data = raw_edid(0) + bytes(256)
        with patch.object(edid, 'wmi_edid', return_value=(data, [])), \
                patch.object(edid, 'registry_edid') as registry:
            result = edid.read_edid(IDENTITY)
        registry.assert_not_called()
        self.assertEqual(base64.b64decode(result['dataBase64']), data)
        self.assertIsNone(result['expectedLength'])
        self.assertFalse(result['complete'])
        self.assertTrue(result['checksumsValid'])
        self.assertEqual(result['warnings'], [])

    def test_any_wmi_bytes_skip_longer_cache(self):
        for full in (raw_edid(3), override_edid()):
            with self.subTest(), patch.object(edid, 'wmi_edid', return_value=(full[:256], [])), \
                    patch.object(edid, 'registry_edid', return_value=full) as registry:
                result = edid.read_edid(IDENTITY)
            registry.assert_not_called()
            self.assertEqual(result['source'], 'wmi')
            self.assertEqual(base64.b64decode(result['dataBase64']), full[:256])
            self.assertEqual(result['warnings'], [])

    def test_override_checksum_failure_remains_a_separate_warning(self):
        data = bytearray(override_edid())
        data[255] ^= 1
        result = edid.describe_edid(data, 'wmi')
        self.assertFalse(result['checksumsValid'])
        self.assertIn('checksum', result['warnings'][0])

    def test_three_blocks_and_larger_edid_are_not_truncated(self):
        for count in (0, 1, 2, 5, 255):
            data = raw_edid(count)
            result = edid.describe_edid(data, 'wmi')
            self.assertTrue(result['checksumsValid'])
            self.assertEqual(result['byteLength'], len(data))
            self.assertEqual(base64.b64decode(result['dataBase64']), data)
            self.assertEqual(result['warnings'], [])

    def test_incomplete_and_checksum_error_are_preserved(self):
        truncated = raw_edid(2)[:256]
        result = edid.describe_edid(truncated, 'wmi')
        self.assertEqual(result['warnings'], [])
        self.assertEqual(base64.b64decode(result['dataBase64']), truncated)
        damaged = bytearray(raw_edid(2))
        damaged[130] = 1
        result = edid.describe_edid(bytes(damaged), 'wmi')
        self.assertFalse(result['checksumsValid'])
        self.assertTrue(result['warnings'])

    def test_wmi_worker_is_bounded_and_uses_only_fixed_script(self):
        data = raw_edid(2)
        with patch.object(edid.subprocess, 'run', return_value=SimpleNamespace(
                stdout=output_for(data), returncode=0)) as run:
            actual, warnings = edid.wmi_edid(IDENTITY)
        self.assertEqual(actual, data)
        self.assertEqual(warnings, [])
        self.assertEqual(run.call_args.kwargs['timeout'], 8)
        self.assertEqual(json.loads(run.call_args.kwargs['input']), r'DISPLAY\DEL1234\4&1234&0&UID123')
        self.assertNotIn(IDENTITY, run.call_args.args[0])
        script = base64.b64decode(run.call_args.args[0][-1]).decode('utf-16-le')
        self.assertIn('$index -lt 256', script)
        self.assertIn('WmiGetMonitorRawEEdidV1Block', script)
        self.assertEqual(run.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    def test_timeout_preserves_successful_blocks_and_is_not_retried(self):
        data = raw_edid(2)[:256]
        timeout = subprocess.TimeoutExpired('powershell', 8, output=output_for(data))
        with patch.object(edid.subprocess, 'run', side_effect=timeout) as run:
            actual, warnings = edid.wmi_edid(IDENTITY)
        self.assertEqual(actual, data)
        self.assertIn('8 seconds', warnings[0])
        run.assert_called_once()

    def test_timeout_after_declaration_retains_extra_blocks_and_warning(self):
        data = raw_edid(0) + bytes(256)
        timeout = subprocess.TimeoutExpired('powershell', 8, output=output_for(data))
        with patch.object(edid.subprocess, 'run', side_effect=timeout), \
                patch.object(edid, 'registry_edid') as registry:
            result = edid.read_edid(IDENTITY)
        registry.assert_not_called()
        self.assertEqual(base64.b64decode(result['dataBase64']), data)
        self.assertTrue(any('8 seconds' in warning for warning in result['warnings']))

    def test_noncontiguous_blocks_are_not_concatenated(self):
        lines = output_for(raw_edid(2)).splitlines()
        with patch.object(edid.subprocess, 'run', return_value=SimpleNamespace(
                stdout=b'\n'.join((lines[0], lines[2])), returncode=0)):
            data, warnings = edid.wmi_edid(IDENTITY)
        self.assertEqual(len(data), 128)
        self.assertTrue(warnings)

    def test_fallback_uses_whole_registry_data_and_labels_cache(self):
        data = raw_edid(2)
        with patch.object(edid, 'wmi_edid', return_value=(b'', ['Block 0 failed.'])), \
                patch.object(edid, 'registry_edid', return_value=data):
            result = edid.read_edid(IDENTITY)
        self.assertEqual(result['source'], 'registry')
        self.assertEqual(base64.b64decode(result['dataBase64']), data)
        self.assertIn('cached driver data', result['warnings'][-1])

    def test_read_failure_after_some_wmi_blocks_keeps_bytes_and_warning(self):
        data = raw_edid(2)[:256]
        with patch.object(edid, 'wmi_edid', return_value=(data, ['Block 2 failed.'])), \
                patch.object(edid, 'registry_edid', return_value=data[:128]):
            result = edid.read_edid(IDENTITY)
        self.assertEqual(result['source'], 'wmi')
        self.assertEqual(result['byteLength'], 256)
        self.assertIn('Block 2 failed.', result['warnings'])
        with patch.object(edid, 'wmi_edid', side_effect=OSError('unavailable')), \
                patch.object(edid, 'registry_edid', side_effect=OSError('not found')):
            result = edid.read_edid(IDENTITY)
        self.assertEqual(result['source'], 'unavailable')
        self.assertEqual(result['dataBase64'], '')
        self.assertTrue(result['warnings'])


class EdidWmiScriptTests(unittest.TestCase):
    def run_script(self, statuses, blocks=None, block_types=None, repeat=False, trace=None):
        blocks = blocks if blocks is not None else [raw_edid(2)[i:i + 128] for i in range(0, 384, 128)]
        encoded = base64.b64encode(json.dumps([base64.b64encode(block).decode('ascii')
                                               for block in blocks]).encode()).decode('ascii')
        mock_script = r'''
$script:blocks = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('BLOCKS')) | ConvertFrom-Json
$script:statuses = @(STATUSES)
$script:types = @(TYPES)
function Get-CimInstance {
    param($Namespace, $ClassName)
    [PSCustomObject]@{Active=$true; InstanceName='DISPLAY\DEL1234\4&1234&0&UID123_0'}
}
function Invoke-CimMethod {
    param($InputObject, $MethodName, $Arguments)
    $index = [int]$Arguments.BlockId
    if (REPEAT) { $index = 0 }
    if ($index -ge $script:blocks.Count) { throw 'No more EDID blocks.' }
    [PSCustomObject]@{ReturnValue=$script:statuses[$index]; BlockType=$script:types[$index]; BlockContent=[Convert]::FromBase64String($script:blocks[$index])}
}
'''.replace('BLOCKS', encoded).replace('STATUSES', ', '.join(statuses)).replace(
            'TYPES', ', '.join(str(value) for value in (block_types or [255] * len(blocks)))).replace(
            'REPEAT', '$true' if repeat else '$false')
        with patch.object(edid, 'WMI_SCRIPT', mock_script + edid.WMI_SCRIPT):
            return edid.wmi_edid(IDENTITY, trace)

    def test_script_trace_preserves_per_block_times_and_normal_exception_end(self):
        trace = []
        data, warnings = self.run_script(['$true'] * 3, trace=trace)
        self.assertEqual(data, raw_edid(2))
        self.assertEqual(warnings, [])
        self.assertEqual([event['result'] for event in trace], ['read', 'read', 'read', 'end'])
        self.assertTrue(all(event['elapsedMs'] >= 0 for event in trace))
        self.assertTrue(all(event['blockType'] == 255 and event['byteLength'] == 128 for event in trace[:3]))
        self.assertEqual(trace[-1]['block'], 3)
        self.assertIn('No more EDID blocks', trace[-1]['reason'])

    def test_script_trace_keeps_status_end_without_creating_warning(self):
        trace = []
        data, warnings = self.run_script(['$true', '$true'], [raw_edid(0), bytes(128)], [1, 0], trace=trace)
        self.assertEqual(data, raw_edid(0))
        self.assertEqual(warnings, [])
        self.assertEqual(trace[-1]['result'], 'end')
        self.assertEqual(trace[-1]['blockType'], 0)
        self.assertIn('block type 0', trace[-1]['reason'])

    def test_all_available_blocks_are_read_even_if_declared_count_is_too_small(self):
        for declared in (0, 1):
            raw = raw_edid(declared)[:128] + bytes(384)
            data, warnings = self.run_script(['$true'] * 4,
                                            [raw[i:i + 128] for i in range(0, 512, 128)])
            self.assertEqual(data, raw)
            self.assertEqual(warnings, [])
            self.assertEqual(edid.describe_edid(data, 'wmi')['warnings'], [])

    def test_uninitialized_type_stops_without_appending_returned_bytes(self):
        for declared in (0, 2):
            blocks = [raw_edid(declared)[:128], bytes(128), bytes(128)]
            data, warnings = self.run_script(['$true'] * 3, blocks, [1, 0, 255])
            self.assertEqual(data, blocks[0])
            self.assertEqual(warnings, [])

    def test_invalid_type_or_length_after_declared_end_is_still_a_warning(self):
        blocks = [raw_edid(0), bytes(128)]
        trace = []
        data, warnings = self.run_script(['$true'] * 2, blocks, [1, 99], trace=trace)
        self.assertEqual(data, blocks[0])
        self.assertIn('invalid WMI block type', warnings[0])
        self.assertEqual(trace[-1]['blockType'], 99)
        self.assertEqual(trace[-1]['result'], 'error')
        trace = []
        data, warnings = self.run_script(['$true'] * 2, [blocks[0], bytes(64)], trace=trace)
        self.assertEqual(data, blocks[0])
        self.assertIn('did not contain 128 bytes', warnings[0])
        self.assertEqual(trace[-1]['byteLength'], 64)

    def test_256_block_limit_retains_repeated_blocks_and_warns(self):
        trace = []
        data, warnings = self.run_script(['$true'], [raw_edid(0)], repeat=True, trace=trace)
        self.assertEqual(data, raw_edid(0) * 256)
        self.assertEqual(len(data), 32768)
        self.assertIn('256-block limit', warnings[0])
        self.assertEqual(len(trace), 257)
        self.assertEqual(trace[-1]['block'], 256)
        self.assertEqual(trace[-1]['result'], 'limit')
        self.assertIn('256-block limit', trace[-1]['reason'])

    def test_failure_status_after_declared_end_is_normal_availability_end(self):
        data, warnings = self.run_script(['$true', '$false'], [raw_edid(0), bytes(128)])
        self.assertEqual(data, raw_edid(0))
        self.assertEqual(warnings, [])

    def test_method_exception_after_first_block_is_recorded_in_trace(self):
        trace = []
        data, warnings = self.run_script(['$true'], [raw_edid(2)[:128]], trace=trace)
        self.assertEqual(data, raw_edid(2)[:128])
        self.assertEqual(warnings, [])
        self.assertIn('No more EDID blocks', trace[-1]['reason'])

    def test_boolean_success_reads_all_declared_blocks(self):
        data, warnings = self.run_script(['$true'] * 3)
        self.assertEqual(data, raw_edid(2))
        self.assertEqual(warnings, [])
        self.assertTrue(edid.describe_edid(data, 'wmi')['checksumsValid'])

    def test_override_does_not_limit_available_block_reading(self):
        for count, base in ((2, 1), (5, 1), (1, 5)):
            raw = override_edid(count, base)
            blocks = [raw[i:i + 128] for i in range(0, len(raw), 128)]
            with self.subTest(count=count, base=base):
                data, warnings = self.run_script(['$true'] * len(blocks), blocks)
                self.assertEqual(data, raw)
                self.assertEqual(warnings, [])

    def test_override_does_not_trigger_length_warning(self):
        raw = override_edid()
        blocks = [raw[i:i + 128] for i in range(0, len(raw), 128)]
        data, warnings = self.run_script(['$true', '$true', '$false'], blocks)
        self.assertEqual(data, raw[:256])
        self.assertEqual(edid.describe_edid(data, 'wmi', warnings)['warnings'], [])

    def test_malformed_override_does_not_prevent_probing_to_api_end(self):
        for offset, value in ((128, 0x70), (129, 2), (130, 6), (130, 128),
                              (132, 0xe1), (132, 0xe3), (133, 0), (134, 0)):
            with self.subTest(offset=offset, value=value):
                raw = bytearray(override_edid())
                raw[offset] = value
                data, warnings = self.run_script(['$true', '$true', '$false'],
                                                  [bytes(raw[:128]), bytes(raw[128:256])])
                self.assertEqual(data, raw[:256])
                self.assertEqual(warnings, [])

    def test_numeric_zero_and_mixed_boolean_success_are_accepted(self):
        for statuses in (['[uint32]0'] * 3, ['0', '$true', '[long]0']):
            with self.subTest(statuses=statuses):
                data, warnings = self.run_script(statuses)
                self.assertEqual(data, raw_edid(2))
                self.assertEqual(warnings, [])

    def test_false_nonzero_null_and_string_statuses_do_not_succeed(self):
        for status in ('$false', '[uint32]1', '$null', "'0'", "'True'"):
            with self.subTest(status=status):
                data, warnings = self.run_script([status] * 3)
                self.assertEqual(data, b'')
                self.assertIn('WMI status', warnings[0])

    def test_failed_later_block_preserves_previous_raw_bytes(self):
        data, warnings = self.run_script(['$true', '$false', '$true'])
        self.assertEqual(data, raw_edid(2)[:128])
        self.assertEqual(warnings, [])

    def test_success_status_does_not_accept_wrong_block_length(self):
        data, warnings = self.run_script(['$true'] * 3, [raw_edid(2)[:128], bytes(64), bytes(128)])
        self.assertEqual(data, raw_edid(2)[:128])
        self.assertIn('block 1 did not contain 128 bytes', warnings[0])


class EdidServiceTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller()
        self.reader = Mock(return_value=edid.describe_edid(raw_edid(2), 'wmi'))
        self.input, self.writer, self.hdr, self.window = Mock(), Mock(), Mock(), Mock()
        self.service = ports.DisplayPortService(Renderer(), lambda: self.controller,
            self.input, self.hdr, self.window, self.writer, self.reader)
        self.request = {'version': 1, 'id': 'edid', 'command': 'get_display_edid',
                        'targetKey': '00000000:00000063/1', 'monitorDevicePath': 'monitor-1'}

    def test_read_only_endpoint_does_not_touch_ddc_renderer_hdr_or_output(self):
        result = self.service.dispatch(self.request)
        self.reader.assert_called_once_with('monitor-1')
        self.assertEqual(result['byteLength'], 384)
        self.assertEqual(result['targetKey'], self.request['targetKey'])
        for method in (self.input, self.writer, self.hdr, self.window):
            method.assert_not_called()
        self.assertEqual(self.controller.trials, [])
        self.assertFalse(self.service.busy())

    def test_wrong_identity_multiple_outputs_busy_and_extra_fields_reject_before_read(self):
        with self.assertRaises(ValueError):
            self.service.dispatch({**self.request, 'monitorDevicePath': 'wrong'})
        with self.assertRaises(ValueError):
            self.service.dispatch({**self.request, 'allowInterrupt': True})
        self.service.controller_factory = MultiController
        with self.assertRaises(ValueError):
            self.service.dispatch({**self.request, 'id': 'multi'})
        self.service.running = True
        with self.assertRaises(ValueError):
            self.service.dispatch({**self.request, 'id': 'busy'})
        self.reader.assert_not_called()

    def test_identity_change_during_read_rejects_result(self):
        def changed(identity):
            self.controller.current = 2
            return edid.describe_edid(raw_edid(2), 'wmi')
        self.reader.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'changed during EDID'):
            self.service.dispatch(self.request)
        self.assertFalse(self.service.busy())

    def test_http_uses_edid_envelope_and_is_not_a_mutation(self):
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
            self.assertTrue(result['ok'])
            self.assertEqual(result['edid']['byteLength'], 384)
            self.assertNotIn('get_display_edid', server.MUTATION_COMMANDS)
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
