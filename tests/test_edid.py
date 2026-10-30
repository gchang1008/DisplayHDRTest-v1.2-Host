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


class EdidReaderTests(unittest.TestCase):
    def test_three_blocks_and_larger_edid_are_not_truncated(self):
        for count in (0, 1, 2, 5, 255):
            data = raw_edid(count)
            result = edid.describe_edid(data, 'wmi')
            self.assertTrue(result['complete'])
            self.assertTrue(result['checksumsValid'])
            self.assertEqual(result['expectedLength'], len(data))
            self.assertEqual(base64.b64decode(result['dataBase64']), data)
            self.assertEqual(result['warnings'], [])

    def test_incomplete_and_checksum_error_are_preserved(self):
        truncated = raw_edid(2)[:256]
        result = edid.describe_edid(truncated, 'wmi')
        self.assertFalse(result['complete'])
        self.assertEqual(result['expectedLength'], 384)
        self.assertEqual(base64.b64decode(result['dataBase64']), truncated)
        damaged = bytearray(raw_edid(2))
        damaged[130] = 1
        result = edid.describe_edid(bytes(damaged), 'wmi')
        self.assertTrue(result['complete'])
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
        self.assertIn('$count = 1 + [int]$block[126]', script)
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

    def test_noncontiguous_blocks_are_not_concatenated(self):
        lines = output_for(raw_edid(2)).splitlines()
        with patch.object(edid.subprocess, 'run', return_value=SimpleNamespace(
                stdout=b'\n'.join((lines[0], lines[2])), returncode=0)):
            data, warnings = edid.wmi_edid(IDENTITY)
        self.assertEqual(len(data), 128)
        self.assertTrue(warnings)

    def test_fallback_uses_whole_registry_data_and_labels_cache(self):
        data = raw_edid(2)
        with patch.object(edid, 'wmi_edid', return_value=(data[:256], ['Block 2 failed.'])), \
                patch.object(edid, 'registry_edid', return_value=data):
            result = edid.read_edid(IDENTITY)
        self.assertEqual(result['source'], 'registry')
        self.assertTrue(result['complete'])
        self.assertEqual(base64.b64decode(result['dataBase64']), data)
        self.assertIn('cached driver data', result['warnings'][-1])

    def test_read_failure_is_warning_and_partial_wmi_is_not_overwritten_by_shorter_cache(self):
        data = raw_edid(2)[:256]
        with patch.object(edid, 'wmi_edid', return_value=(data, ['Block 2 failed.'])), \
                patch.object(edid, 'registry_edid', return_value=data[:128]):
            result = edid.read_edid(IDENTITY)
        self.assertEqual(result['source'], 'wmi')
        self.assertEqual(result['byteLength'], 256)
        self.assertFalse(result['complete'])
        with patch.object(edid, 'wmi_edid', side_effect=OSError('unavailable')), \
                patch.object(edid, 'registry_edid', side_effect=OSError('not found')):
            result = edid.read_edid(IDENTITY)
        self.assertEqual(result['source'], 'unavailable')
        self.assertEqual(result['dataBase64'], '')
        self.assertTrue(result['warnings'])

    def test_different_cached_base_cannot_replace_current_wmi_data(self):
        data = raw_edid(2)[:256]
        cached = bytearray(raw_edid(2))
        cached[12] = 1
        with patch.object(edid, 'wmi_edid', return_value=(data, [])), \
                patch.object(edid, 'registry_edid', return_value=bytes(cached)):
            result = edid.read_edid(IDENTITY)
        self.assertEqual(result['source'], 'wmi')
        self.assertEqual(base64.b64decode(result['dataBase64']), data)
        self.assertIn('differs from WMI', result['warnings'][0])


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
