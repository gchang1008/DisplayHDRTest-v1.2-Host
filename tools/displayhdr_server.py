"""Launch DisplayHDR and serve its local pipe API over HTTP on the LAN."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import socket
import time
import threading

from displayhdr_api import DisplayHDRClient
from displayhdr_supervisor import Supervisor


def failure(identifier, code, message, uncertain=False):
    return {"version": 1, "id": identifier, "ok": False,
            "error": {"code": code, "message": message, "requestMayHaveApplied": uncertain}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.body_timeout)

    def reply(self, status, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        except (OSError, TimeoutError):
            pass  # A lost HTTP connection must not cancel or replay a pipe command.

    def do_GET(self):
        self.reply(405, failure("", "method_not_allowed", "Use POST /api."))

    def do_POST(self):
        identifier = ""
        request = None
        if self.path != "/api":
            self.reply(404, failure("", "not_found", "Use POST /api."))
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                self.reply(400, failure("", "invalid_request", "Chunked requests are unsupported."))
                return
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                self.reply(411, failure("", "invalid_request", "One Content-Length is required."))
                return
            length = int(lengths[0])
            if length < 1 or length > 16384:
                self.reply(413, failure("", "invalid_request", "Request must be 1 to 16384 bytes."))
                return
            if self.headers.get_content_type() != "application/json":
                self.reply(415, failure("", "invalid_request", "Content-Type must be application/json."))
                return
            try:
                deadline = time.monotonic() + self.server.body_timeout
                raw = bytearray()
                while len(raw) < length:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    self.connection.settimeout(remaining)
                    chunk = self.rfile.read1(length - len(raw))
                    if not chunk:
                        break
                    raw.extend(chunk)
            except TimeoutError:
                self.reply(408, failure("", "request_timeout", "Request body timed out; no command forwarded."))
                return
            if len(raw) != length:
                raise ValueError("Incomplete request body.")
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object.")
            identifier = request.get("id", "")
            if not isinstance(identifier, str):
                identifier = ""
            command = request.get("command")
            if command in ("get_host_status", "restart_host"):
                if type(request.get("version")) is not int or request["version"] != 1 or not identifier or set(request) - {"version", "id", "command"}:
                    raise ValueError("Host commands require version 1, an id, and no additional fields.")
                supervisor = self.server.supervisor
                if command == "restart_host":
                    if supervisor is None:
                        raise ValueError("Restart requires a managed Host launcher.")
                    supervisor.restart()
                host = supervisor.status() if supervisor else {"status": "ready", "pid": self.server.pid,
                                                                "restartSupported": False, "error": ""}
                self.reply(200, {"version": 1, "id": identifier, "ok": True, "host": host})
                return
            if self.server.supervisor is not None:
                host = self.server.supervisor.status()
                if host["status"] != "ready":
                    self.reply(503, failure(identifier, "host_unavailable", "Renderer is " + host["status"] + "."))
                    return
                self.server.pid = host["pid"]
            with DisplayHDRClient(self.server.pid, self.server.pipe_timeout) as client:
                response = client.send(request)
            self.reply(200, response)
        except (ValueError, UnicodeError) as error:
            self.reply(400, failure(identifier, "invalid_request", str(error)))
        except TimeoutError as error:
            self.reply(504, failure(identifier, "bridge_timeout", str(error),
                                    isinstance(request, dict) and request.get("command") in ("set_state", "key")))
        except (OSError, ConnectionError) as error:
            self.reply(502, failure(identifier, "bridge_unavailable", str(error),
                                    isinstance(request, dict) and request.get("command") in ("set_state", "key")))

    def log_message(self, *_):
        pass


class Server(HTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_server(host, port, pid, pipe_timeout=5, body_timeout=5):
    # One HTTP request at a time; no background command queue or automatic replay.
    server = Server((host, port), Handler)
    server.pid = pid
    server.supervisor = None
    server.pipe_timeout = pipe_timeout
    server.body_timeout = body_timeout
    return server


def main():
    adjacent = Path(__file__).resolve().parent / "DisplayHDRComplianceTests.exe"
    default_exe = adjacent if adjacent.exists() else Path(__file__).resolve().parents[1] / "build-output/automation-x64-Release/DisplayHDRComplianceTests.exe"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=default_exe)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pid", type=int, help="Attach to an existing --api instance instead of launching.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be 1 to 65535.")
    if args.pid is not None and args.pid <= 0:
        parser.error("PID must be positive.")
    if args.pid is None and not args.exe.is_file():
        parser.error(f"Executable not found: {args.exe}")
    # Bind before launching so port errors do not leave a new program running.
    with create_server(args.host, args.port, args.pid) as server:
        supervisor = Supervisor(args.exe, args.pid)
        server.supervisor = supervisor
        def start_renderer():
            supervisor.start()
            host = supervisor.status()
            print(f"{'READY' if host['status'] == 'ready' else 'SERVICE'} pid={host['pid']} "
                  f"endpoint=http://{args.host}:{args.port}/api status={host['status']}", flush=True)

        threading.Thread(target=start_renderer, daemon=True).start()
        server.serve_forever(poll_interval=.2)
        # Stopping the network service preserves the running test and its state.


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(f"ERROR: {error}", flush=True)
        raise SystemExit(1)
