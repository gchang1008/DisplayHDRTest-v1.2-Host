"""Manual display-port operations outside the official measurement sequence."""
import ctypes as C
import hashlib
import json
import subprocess
import threading
import time
import winreg

from displayhdr_api import DisplayHDRClient
from displayhdr_display_paths import (DisplayPaths, Header, TargetName, QDC_ALL_PATHS,
                                      QDC_ONLY_ACTIVE_PATHS, key)
from displayhdr_hdr_control import HdrControl
from displayhdr_monitor_input import probe_native
from displayhdr_window_presentation import WindowPresentation


COMMANDS = {"get_display_ports", "get_display_port_status", "switch_display_port"}


def edid_hash(device_path):
    parts = device_path.split("#")
    if len(parts) != 4 or not parts[0].endswith("DISPLAY"):
        return ""
    try:
        registry_path = "SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\" + parts[1] + "\\" + parts[2] + "\\Device Parameters"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as registry:
            value, kind = winreg.QueryValueEx(registry, "EDID")
        return hashlib.sha256(value).hexdigest() if kind == winreg.REG_BINARY and value else ""
    except OSError:
        return ""


class Renderer:
    def __init__(self, server):
        self.server = server

    def request(self, command, **fields):
        supervisor = self.server.supervisor
        status = supervisor.status() if supervisor else {"status": "ready", "pid": self.server.pid}
        if status["status"] != "ready":
            raise RuntimeError("Host renderer is not ready.")
        with DisplayHDRClient(status["pid"], timeout=self.server.pipe_timeout) as client:
            response = client.request(command, **fields)
        if response.get("ok") is not True or not isinstance(response.get("state"), dict):
            raise RuntimeError("Host renderer did not confirm the requested state.")
        return response["state"]

    def state(self):
        return self.request("get_state")

    def restart_supported(self):
        return bool(self.server.supervisor and self.server.supervisor.status().get("restartSupported"))

    def restart(self):
        if not self.server.supervisor:
            raise ValueError("Port switching requires a managed Host launcher.")
        before = self.server.supervisor.status()
        if not before.get("restartSupported"):
            raise ValueError("Port switching requires a managed Host launcher.")
        self.server.supervisor.restart()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = self.server.supervisor.status()
            if status["status"] == "ready" and status["pid"] != before["pid"]:
                return {"pidBefore": before["pid"], "pid": status["pid"], "state": self.state()}
            if status["status"] in ("failed", "stopped"):
                raise RuntimeError("Host restart failed: " + status.get("error", ""))
            time.sleep(.1)
        raise TimeoutError("Host restart timed out.")

    def pid(self):
        return self.server.supervisor.status()["pid"]


class DisplayPortService:
    def __init__(self, renderer, controller_factory=DisplayPaths,
                 input_reader=probe_native, hdr_factory=HdrControl, window_factory=WindowPresentation):
        self.renderer = renderer
        self.controller_factory, self.input_reader = controller_factory, input_reader
        self.hdr_factory, self.window_factory = hdr_factory, window_factory
        self.lock = threading.RLock()
        self.closed = False
        self.data = {"supported": False, "targets": [], "activeTargetKey": "", "input": {},
                     "pendingRestore": False, "operation": self.operation()}
        self.seen = set()

    @staticmethod
    def operation():
        return {"operationId": "", "kind": "", "phase": "idle", "error": "", "ready": False,
                "targetKey": "", "inputValue": None, "hdr": False, "calibration": False}

    def status(self):
        with self.lock:
            self.data["pendingRestore"] = False
            result = json.loads(json.dumps({name: self.data[name] for name in
                ("supported", "targets", "activeTargetKey", "input", "pendingRestore")}))
            result["operation"] = {name: value for name, value in self.data["operation"].items()
                if name in {*self.operation(), "state", "window"}}
            if self.data.get("error"):
                result["error"] = self.data["error"]
            return result

    def busy(self):
        with self.lock:
            return self.data["operation"]["phase"] == "running"

    def close(self):
        self.closed = True

    def read_input(self):
        try:
            return self.input_reader()
        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
            return {"ok": False, "currentValue": None, "error": str(error)}

    def inventory(self):
        with self.lock:
            if self.busy():
                return self.status()
            controller = self.controller_factory()
            active = controller.api.query(QDC_ONLY_ACTIVE_PATHS)
            active_keys = {key(path.target) for path in active.paths}
            targets = {}
            for path in controller.api.query(QDC_ALL_PATHS).paths:
                if not path.target.available:
                    continue
                identity = controller.api.device_path(path)
                name = TargetName()
                name.header = Header(2, C.sizeof(name), path.target.adapter, path.target.id)
                controller.api.check(controller.api.dll.DisplayConfigGetDeviceInfo(C.byref(name.header)))
                target_key = key(path.target)
                targets[target_key] = {"targetKey": target_key, "monitorDevicePath": identity,
                    "name": bytes(name.name).decode("utf-16-le").split("\0", 1)[0],
                    "connection": {5: "HDMI", 10: "DisplayPort / USB-C"}.get(path.target.technology, "Other"),
                    "active": target_key in active_keys, "available": True, "edidHash": edid_hash(identity)}
            reading = self.read_input() if len(active_keys) == 1 else {"ok": False, "error": "Enable exactly one display before calibration.", "currentValue": None}
            error = ""
            if not self.renderer.restart_supported():
                error = "Port switching requires a managed Host launcher."
            elif not targets or len(active_keys) != 1:
                error = "Enable exactly one connected display before matching or switching."
            elif not reading.get("ok") or type(reading.get("currentValue")) is not int or not 1 <= reading["currentValue"] <= 255:
                error = reading.get("error") or "DUT input value could not be confirmed."
            elif (reading.get("targetKey") not in active_keys or
                    reading.get("monitorDevicePath") != targets.get(reading.get("targetKey"), {}).get("monitorDevicePath")):
                error = "DDC/CI display identity does not match the active output."
            elif not controller.inspect().get("matchesDatabase"):
                error = "Active and saved display configurations differ; verify Windows display settings."
            self.data.update(targets=list(targets.values()), input=reading,
                             activeTargetKey=next(iter(active_keys)) if len(active_keys) == 1 else "",
                             supported=not error, error=error)
            if self.data["supported"] and self.data["operation"]["phase"] == "failed":
                self.data["operation"] = self.operation()
            return self.status()

    def dispatch(self, request):
        if self.closed:
            raise ValueError("The display-port service has closed.")
        command = request["command"]
        if command not in COMMANDS:
            raise ValueError("Unknown display-port command.")
        common = {"version", "id", "command"}
        fields = (common | {"targetKey", "monitorDevicePath", "expectedInput", "calibration", "allowInterrupt", "autoSwitchConfirmed"}
                  if command == "switch_display_port" else common)
        if set(request) != fields or type(request.get("version")) is not int or request["version"] != 1 or not isinstance(request.get("id"), str) or not request["id"]:
            raise ValueError("Unexpected or missing display-port command fields.")
        if command == "get_display_ports":
            return self.inventory()
        if command == "get_display_port_status":
            return self.status()
        if request["allowInterrupt"] is not True:
            raise ValueError("Explicit allowInterrupt=true is required.")
        if command == "switch_display_port":
            calibration, expected = request["calibration"], request["expectedInput"]
            if (type(calibration) is not bool or request["autoSwitchConfirmed"] is not True
                    or not isinstance(request["targetKey"], str) or not request["targetKey"]
                    or not isinstance(request["monitorDevicePath"], str) or not request["monitorDevicePath"]
                    or (calibration and expected is not None)
                    or (not calibration and (type(expected) is not int or not 1 <= expected <= 255))):
                raise ValueError("Confirm Auto Switch and provide a valid target and calibration/input value.")
        with self.lock:
            if request["id"] == self.data["operation"]["operationId"]:
                if self.data["operation"].get("request") != request:
                    raise ValueError("This operation id belongs to a different request.")
                return self.status()
            if request["id"] in self.seen:
                raise ValueError("This operation id was already used; no command was repeated.")
            if self.busy():
                raise ValueError("A display-port operation is already running.")
            if command == "switch_display_port" and not self.renderer.restart_supported():
                raise ValueError("Port switching requires a managed Host launcher.")
            state = self.renderer.state()
            if state.get("test", {}).get("id") not in ("StartOfTest", "ColorPatchesFull"):
                raise ValueError("Port operations require the start screen or full-screen color preview; stop measurement first.")
            self.seen.add(request["id"])
            self.data["operation"] = {**self.operation(), "operationId": request["id"], "kind": command,
                                      "phase": "running", "targetKey": request.get("targetKey", ""),
                                      "calibration": request.get("calibration", False), "request": request}
            try:
                response = self.status()
                threading.Thread(target=self.work, args=(request,), daemon=True).start()
            except Exception as error:
                self.data["operation"].update(phase="failed", ready=False, error=str(error))
                raise
            return response

    def wait_input(self, target, identity, expected, excluded=None):
        deadline, previous, consecutive = time.monotonic() + 45, None, 0
        samples = []
        reading = {"ok": False, "error": "No input response was received."}
        while time.monotonic() < deadline:
            reading = self.read_input()
            value = reading.get("currentValue")
            valid = (reading.get("ok") is True and reading.get("targetKey") == target
                     and reading.get("monitorDevicePath") == identity and type(value) is int and 1 <= value <= 255
                     and value != excluded
                     and (expected is None or value == expected))
            consecutive = consecutive + 1 if valid and value == previous else 1 if valid else 0
            previous = value if valid else None
            samples.append({"at": time.time(), "input": reading, "matches": valid})
            if consecutive >= 2 and time.monotonic() <= deadline:
                return reading, samples
            time.sleep(min(.5, max(0, deadline - time.monotonic())))
        error = TimeoutError("DUT input could not be confirmed within 45 seconds.")
        error.input_samples, error.last_input = samples, reading
        raise error

    def work(self, request):
        operation = dict(self.data["operation"])
        try:
            controller = self.controller_factory()
            target, identity = request["targetKey"], request["monitorDevicePath"]
            current = controller.inspect()
            if len(current["active"]["paths"]) != 1 or not current.get("matchesDatabase"):
                raise ValueError("Verify exactly one active display and its saved configuration before switching.")
            original_input = self.read_input()
            active = current["active"]["paths"][0]
            if (not original_input.get("ok") or type(original_input.get("currentValue")) is not int
                    or not 1 <= original_input["currentValue"] <= 255
                    or original_input.get("targetKey") != active["targetKey"]
                    or original_input.get("monitorDevicePath") != active.get("monitorDevicePath")):
                raise ValueError("DUT DDC/CI input is unavailable; no port switch was applied.")

            if active["targetKey"] == target and active.get("monitorDevicePath") != identity:
                raise ValueError("Active target identity does not match the requested path.")
            self.renderer.request("set_state", test="StartOfTest", settings={"fullscreen": True})
            if active["targetKey"] != target:
                operation["selection"] = controller.trial(target, identity, None, save_to_database=True)
                operation["portRestart"] = self.renderer.restart()
            hdr = self.hdr_factory().enable(target, identity)
            if hdr.get("changed"):
                operation["hdrRestart"] = self.renderer.restart()
            elif active["targetKey"] == target:
                operation["freshRestart"] = self.renderer.restart()
            excluded = original_input["currentValue"] if request["calibration"] and active["targetKey"] != target else None
            reading, samples = self.wait_input(target, identity, request["expectedInput"], excluded=excluded)
            operation["inputSamples"] = samples
            current = controller.inspect()
            if (len(current["active"]["paths"]) != 1 or current["active"]["paths"][0]["targetKey"] != target
                    or current["active"]["paths"][0].get("monitorDevicePath") != identity or not current.get("matchesDatabase")):
                raise RuntimeError("The selected display configuration changed.")
            active_target = target
            state = self.renderer.request("set_state", settings={"fullscreen": True, "textVisible": False})
            if request["command"] == "switch_display_port" and not state.get("display", {}).get("hdr"):
                raise RuntimeError("HDR mode was not confirmed after the port switch.")
            if not all(state.get("presentation", {}).get(k) is True for k in ("presented", "resourcesValid")):
                raise RuntimeError("Host window presentation was not confirmed.")
            window = self.window_factory().bring_front(self.renderer.pid(), keep_on_top=True)
            if not window.get("unobstructed"):
                raise RuntimeError("Host window is obscured or window status could not be verified.")
            with self.lock:
                self.data.update(input=reading, activeTargetKey=active_target, operation=operation, supported=True, error="")
                operation.update(phase="ready", ready=True, error="", inputValue=reading.get("currentValue"),
                                 hdr=bool(state["display"]["hdr"]), state=state, window=window)
                for item in self.data["targets"]:
                    item["active"] = item["targetKey"] == self.data["activeTargetKey"]
        except Exception as error:
            with self.lock:
                if getattr(error, "report", None):
                    operation["selection"] = error.report
                if getattr(error, "input_samples", None):
                    operation["inputSamples"] = error.input_samples
                    self.data["input"] = error.last_input
                self.data["operation"] = operation
                self.data["operation"].update(phase="failed", ready=False, error=str(error))
