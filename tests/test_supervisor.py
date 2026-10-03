"""Supervisor lifecycle and HTTP control, without modifying the renderer."""
import http.client
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from displayhdr_supervisor import Supervisor
from displayhdr_server import create_server


class Process:
    def __init__(self, pid):
        self.pid = pid
        self.code = None

    def poll(self):
        return self.code


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.processes, self.closed = [], []
        self.fail = False
        self.gate = None

        def launch(exe):
            if self.fail:
                raise FileNotFoundError("missing renderer")
            process = Process(100 + len(self.processes))
            self.processes.append(process)
            return process

        def probe(pid):
            if self.gate:
                self.gate.wait(2)

        def close(process):
            self.closed.append(process)
            process.code = 0

        self.supervisor = Supervisor("renderer.exe", launcher=launch, checker=probe, closer=close)
        self.supervisor.start()

    def wait_ready(self):
        import time
        end = time.monotonic() + 3
        while self.supervisor.status()["status"] in ("starting", "restarting") and time.monotonic() < end:
            time.sleep(.01)
        self.assertEqual(self.supervisor.status()["status"], "ready")

    def test_restart_closes_only_owned_process_and_changes_pid(self):
        before = self.supervisor.status()
        self.supervisor.restart()
        self.wait_ready()
        self.assertNotEqual(before["pid"], self.supervisor.status()["pid"])
        self.assertEqual(self.closed, [self.processes[0]])

    def test_exit_does_not_restart_automatically(self):
        self.processes[0].code = 0
        self.assertEqual(self.supervisor.status()["status"], "stopped")
        self.assertEqual(len(self.processes), 1)
        self.supervisor.restart()
        self.wait_ready()

    def test_crash_and_launch_failure_can_be_recovered(self):
        self.processes[0].code = 9
        self.assertEqual(self.supervisor.status()["status"], "failed")
        self.fail = True
        self.supervisor.restart()
        import time
        end = time.monotonic() + 3
        while self.supervisor.status()["status"] in ("starting", "restarting") and time.monotonic() < end:
            time.sleep(.01)
        self.assertEqual(self.supervisor.status()["status"], "failed")
        self.assertIn("missing renderer", self.supervisor.status()["error"])
        self.fail = False
        self.supervisor.restart()
        self.wait_ready()

    def test_failed_probe_cleans_up_new_process(self):
        self.supervisor.checker = lambda pid: (_ for _ in ()).throw(TimeoutError("startup timeout"))
        self.supervisor.restart()
        import time
        end = time.monotonic() + 3
        while self.supervisor.status()["status"] in ("starting", "restarting") and time.monotonic() < end:
            time.sleep(.01)
        self.assertEqual(self.supervisor.status()["status"], "failed")
        self.assertEqual(self.closed, self.processes)

    def test_duplicate_restart_is_rejected(self):
        self.gate = threading.Event()
        self.supervisor.restart()
        try:
            with self.assertRaises(ValueError):
                self.supervisor.restart()
        finally:
            self.gate.set()
        self.wait_ready()

    def test_attached_pid_cannot_be_restarted(self):
        attached = Supervisor("renderer.exe", pid=os.getpid(), checker=lambda pid: None)
        attached.start()
        self.assertEqual(attached.status()["status"], "ready")
        self.assertFalse(attached.status()["restartSupported"])
        with self.assertRaises(ValueError):
            attached.restart()

    def test_attached_process_exit_updates_status(self):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        for code, phase in ((0, "stopped"), (7, "failed"), (259, "failed")):
            with self.subTest(code=code), subprocess.Popen(
                    [sys.executable, "-c", "import sys; sys.stdin.readline(); sys.exit(int(sys.argv[1]))", str(code)],
                    stdin=subprocess.PIPE, startupinfo=startup) as process:
                attached = Supervisor("renderer.exe", pid=process.pid, checker=lambda pid: None,
                                      closer=lambda _: self.fail("Attached process must not be closed."))
                attached.start()
                self.assertEqual(attached.status()["status"], "ready")
                process.stdin.write(b"\n")
                process.stdin.flush()
                process.wait(timeout=5)
                status = attached.status()
                self.assertEqual(status["status"], phase)
                self.assertEqual(status["pid"], process.pid)
                self.assertFalse(status["restartSupported"])
                attached.attached_process.close()

    def test_failed_attached_probe_releases_handle_without_stopping_process(self):
        attached = Supervisor("renderer.exe", pid=os.getpid(),
                              checker=lambda pid: (_ for _ in ()).throw(TimeoutError("probe failed")),
                              closer=lambda _: self.fail("Attached process must not be closed."))
        attached.start()
        self.assertEqual(attached.status()["status"], "failed")
        self.assertIsNone(attached.attached_process)

    def test_http_status_and_restart_remain_available(self):
        server = create_server("127.0.0.1", 0, 100)
        server.supervisor = self.supervisor
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def post(command, **fields):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            request = {"version": 1, "id": "test", "command": command, **fields}
            connection.request("POST", "/api", json.dumps(request), {"Content-Type": "application/json"})
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        try:
            self.assertEqual(post("get_host_status")[1]["host"]["status"], "ready")
            self.gate = threading.Event()
            self.assertTrue(post("restart_host")[1]["ok"])
            self.assertIn(post("get_host_status")[1]["host"]["status"], ("starting", "restarting"))
            self.assertEqual(post("get_state")[0], 503)
            self.assertEqual(post("restart_host")[0], 400)
            self.assertEqual(post("get_host_status", settings={})[0], 400)
            self.assertEqual(post("get_host_status", version=True)[0], 400)
            self.gate.set()
            self.wait_ready()
            self.assertEqual(post("get_host_status")[1]["host"]["pid"], 101)
        finally:
            if self.gate:
                self.gate.set()
            server.shutdown()
            server.server_close()
            worker.join(3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
