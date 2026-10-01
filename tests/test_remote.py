"""Run the existing API contract through HTTP and check network failure paths."""
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import test_automation
from http_client import HttpClient as DisplayHDRRemoteClient
from displayhdr_server import create_server


class TestClient(DisplayHDRRemoteClient):
    def close(self):
        pass  # The parent fixture expects close; HTTP requests already close their sockets.


class RemoteTests(test_automation.AutomationTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client.close()
        cls.server = create_server("127.0.0.1", 0, cls.server_pid, body_timeout=.2)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.client = TestClient(cls.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)
        super().tearDownClass()

    def raw(self, body, path="/api", method="POST", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_protocol_errors_and_reconnection(self):
        self.assertFalse(self.client.send({"version": 2, "id": "wrong-version", "command": "get_state"})["ok"])
        self.assertFalse(self.client.request("unknown_command")["ok"])
        self.assertFalse(self.client.request("get_state", settings={})["ok"])
        type(self).client = TestClient(self.url)
        self.assertTrue(self.client.request()["ok"])

    def test_http_input_rejections_preserve_state(self):
        before = self.state(test="ColorPatchesFull", settings={"color": "Blue", "paused": True})
        for body, expected in ((b"{bad", 400), (b"[]", 400), (b"\xff", 400),
                               (b"x" * 16385, 413), (b"", 413)):
            status, response = self.raw(body)
            self.assertEqual(status, expected)
            self.assertFalse(response["ok"])
        self.assertEqual(self.raw(b"{}", path="/wrong")[0], 404)
        self.assertEqual(self.raw(None, method="GET")[0], 405)
        self.assertEqual(self.raw(b"{}", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(before["settings"], self.state()["settings"])
        self.assertEqual(before["test"], self.state()["test"])

    def test_partial_body_timeout_does_not_forward(self):
        before = self.state(test="ColorPatches", settings={"color": "Green"})
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
            connection.sendall(b"POST /api HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{")
            response = http.client.HTTPResponse(connection)
            response.begin()
            self.assertEqual(response.status, 408)
            self.assertFalse(json.loads(response.read())["error"]["requestMayHaveApplied"])
        self.assertEqual(self.state()["settings"], before["settings"])

    def test_disconnect_after_command_has_no_replay(self):
        self.state(test="ColorPatches", settings={"color": "Red"})
        command = {"version": 1, "id": "remote-disconnect", "command": "set_state",
                   "test": "ColorPatchesFull", "settings": {"color": "Blue"}}
        body = json.dumps(command).encode()
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
            connection.sendall(f"POST /api HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
        state = self.state()
        self.assertEqual(state["lastSetRequestId"], "remote-disconnect")
        self.assertEqual(state["settings"]["color"], "Blue")
        self.assertEqual(state["test"]["id"], "ColorPatchesFull")
        self.assertEqual(state["stateVersion"], self.state()["stateVersion"])

    def test_partial_body_activity_does_not_extend_deadline(self):
        before = self.state(test="ColorPatches", settings={"color": "Blue"})
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
            connection.sendall(b"POST /api HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{")
            time.sleep(.12)
            connection.sendall(b" ")
            response = http.client.HTTPResponse(connection)
            response.begin()
            self.assertEqual(response.status, 408)
            response.read()
        self.assertEqual(before["settings"], self.state()["settings"])

    def test_bridge_failure_never_retries(self):
        for error, status in ((TimeoutError("test timeout"), 504), (ConnectionError("test disconnect"), 502)):
            with patch("displayhdr_server.DisplayHDRClient", side_effect=error) as pipe:
                code, response = self.raw(json.dumps({"version": 1, "id": "uncertain", "command": "set_state"}).encode())
                self.assertEqual(code, status)
                self.assertEqual(response["id"], "uncertain")
                self.assertTrue(response["error"]["requestMayHaveApplied"])
                pipe.assert_called_once()
        with patch("displayhdr_server.DisplayHDRClient", side_effect=TimeoutError("key timeout")) as pipe:
            code, response = self.raw(json.dumps({"version": 1, "id": "uncertain-key", "command": "key", "key": "Up"}).encode())
            self.assertEqual(code, 504)
            self.assertTrue(response["error"]["requestMayHaveApplied"])
            pipe.assert_called_once()
        self.assertTrue(self.client.request()["ok"])

    def test_port_conflict_is_rejected(self):
        with self.assertRaises(OSError):
            create_server("127.0.0.1", self.server.server_port, self.server_pid)

    def test_stopping_service_keeps_original_process_and_state(self):
        before = self.state(test="ColorPatches", settings={"color": "White"})
        temporary = create_server("127.0.0.1", 0, self.server_pid)
        worker = threading.Thread(target=temporary.serve_forever, daemon=True)
        worker.start()
        temporary.shutdown()
        temporary.server_close()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(before["settings"], self.state()["settings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
