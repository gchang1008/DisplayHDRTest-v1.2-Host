"""Manual display-port operations outside the official measurement sequence."""
import ctypes as C
import hashlib
import json
import math
import subprocess
import threading
import time
import winreg

from displayhdr_api import DisplayHDRClient
from displayhdr_display_paths import (DisplayPaths, Header, TargetName, QDC_ALL_PATHS,
                                      QDC_ONLY_ACTIVE_PATHS, key)
from displayhdr_hdr_control import HdrControl
from displayhdr_monitor_input import InputIdentityError, probe_native, write_native
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

    def catalog(self):
        status = self.server.supervisor.status() if self.server.supervisor else {"status": "ready", "pid": self.server.pid}
        if status["status"] != "ready":
            raise RuntimeError("Host renderer is not ready.")
        with DisplayHDRClient(status["pid"], timeout=self.server.pipe_timeout) as client:
            response = client.request("catalog")
        if response.get("ok") is not True or not isinstance(response.get("catalog"), dict):
            raise RuntimeError("Host renderer did not provide its settings catalog.")
        return response["catalog"]

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
                 input_reader=probe_native, hdr_factory=HdrControl, window_factory=WindowPresentation,
                 input_writer=write_native):
        self.renderer = renderer
        self.controller_factory, self.input_reader = controller_factory, input_reader
        self.hdr_factory, self.window_factory = hdr_factory, window_factory
        self.input_writer = input_writer
        self.switch_mode = "pair"
        self.skip_ddc = False
        self.lock = threading.RLock()
        self.closed = False
        self.data = {"supported": False, "manualSupported": False, "targets": [], "activeTargetKey": "", "input": {},
                     "pendingRestore": False, "operation": self.operation()}
        self.seen = set()

    @staticmethod
    def operation():
        return {"operationId": "", "kind": "", "phase": "idle", "error": "", "ready": False,
                "targetKey": "", "inputValue": None, "hdr": False, "calibration": False,
                "verificationMode": "ddc", "inputVerified": False, "inputUnavailable": False,
                "switchMode": "pair", "waitSeconds": 0, "waitRemainingSeconds": 0, "timedReady": False, "stableSeconds": 0}

    def status(self):
        with self.lock:
            self.data["pendingRestore"] = False
            result = json.loads(json.dumps({name: self.data[name] for name in
                ("supported", "manualSupported", "targets", "activeTargetKey", "input", "pendingRestore")}))
            result["switchModes"] = ["active", "passive"]
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
        if self.switch_mode == "passive" or self.skip_ddc:
            return {"ok": False, "currentValue": None, "intentionallySkipped": True,
                    "error": "Passive mode does not query DDC/CI."}
        try:
            return self.input_reader()
        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
            return {"ok": False, "currentValue": None, "error": str(error),
                    "identityMismatch": isinstance(error, InputIdentityError)}

    def inventory(self, switch_mode=None):
        with self.lock:
            if self.busy():
                return self.status()
            if switch_mode is not None:
                self.switch_mode = switch_mode
                self.skip_ddc = switch_mode == "passive"
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
            elif not targets or len(active_keys) != 1 or not active_keys.issubset(targets):
                error = "Enable exactly one connected display before matching or switching."
            elif reading.get("identityMismatch") is True:
                error = reading.get("error") or "Native display identity could not be verified."
            elif (reading.get("ok") is True and (reading.get("targetKey") not in active_keys or
                    reading.get("monitorDevicePath") != targets.get(reading.get("targetKey"), {}).get("monitorDevicePath"))):
                error = "DDC/CI display identity does not match the active output."
            elif not controller.inspect().get("matchesDatabase"):
                error = "Active and saved display configurations differ; verify Windows display settings."
            manual_supported = not error
            if self.switch_mode != "passive" and not error and (not reading.get("ok") or type(reading.get("currentValue")) is not int
                              or not 1 <= reading["currentValue"] <= 255):
                error = reading.get("error") or "DUT input value could not be confirmed."
            self.data.update(targets=list(targets.values()), input=reading,
                             activeTargetKey=next(iter(active_keys)) if len(active_keys) == 1 else "",
                             supported=not error, manualSupported=manual_supported, error=error)
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
        for optional in (("verificationMode", "switchMode", "passiveWaitSeconds") if command == "switch_display_port" else ("switchMode",) if command in ("get_display_ports", "get_display_port_status") else ()):
            if optional in request:
                fields.add(optional)
        mode = request.get("switchMode", "pair")
        if mode not in ("pair", "active", "passive"):
            raise ValueError("Unknown input switch mode.")
        if set(request) != fields or type(request.get("version")) is not int or request["version"] != 1 or not isinstance(request.get("id"), str) or not request["id"]:
            raise ValueError("Unexpected or missing display-port command fields.")
        if command == "get_display_ports":
            return self.inventory(mode)
        if command == "get_display_port_status":
            return self.status()
        if request["allowInterrupt"] is not True:
            raise ValueError("Explicit allowInterrupt=true is required.")
        if command == "switch_display_port":
            calibration, expected = request["calibration"], request["expectedInput"]
            verification = request.get("verificationMode", "ddc")
            wait = request.get("passiveWaitSeconds", 15)
            if (type(wait) not in (int, float) or not math.isfinite(wait) or not 1 <= wait <= 600
                    or mode == "active" and (calibration or verification != "ddc")
                    or mode == "passive" and (verification != "manual" or expected is not None)):
                raise ValueError("Invalid switch mode or passive waiting time.")
            if (verification not in ("ddc", "manual") or type(calibration) is not bool or (mode != "active" and request["autoSwitchConfirmed"] is not True)
                    or type(request["autoSwitchConfirmed"]) is not bool
                    or not isinstance(request["targetKey"], str) or not request["targetKey"]
                    or not isinstance(request["monitorDevicePath"], str) or not request["monitorDevicePath"]
                    or ((calibration or verification == "manual") and expected is not None)
                    or (not calibration and verification == "ddc" and (type(expected) is not int or not 1 <= expected <= 255))):
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
            if mode not in ("active", "passive") and state.get("test", {}).get("id") not in ("StartOfTest", "ColorPatchesFull"):
                raise ValueError("Port operations require the start screen or full-screen color preview; stop measurement first.")
            self.seen.add(request["id"])
            self.data["operation"] = {**self.operation(), "operationId": request["id"], "kind": command,
                                      "phase": "running", "targetKey": request.get("targetKey", ""),
                                      "calibration": request.get("calibration", False), "request": request,
                                      "verificationMode": request.get("verificationMode", "ddc"),
                                      "switchMode": mode, "waitSeconds": wait if mode == "passive" else 10 if mode == "active" else 0}
            self.switch_mode = mode
            self.skip_ddc = mode == "passive" or ("switchMode" in request and mode == "pair" and request.get("verificationMode") == "manual")
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

    def wait_ready(self, controller, target, identity, expected, operation, mode, reading):
        duration = operation["waitSeconds"]
        deadline = time.monotonic() + duration + 45
        stable_since = None
        pid = self.renderer.pid()
        while time.monotonic() < deadline:
            if self.closed:
                raise RuntimeError("Input service closed while waiting for readiness.")
            current = controller.inspect()
            state = self.renderer.state()
            window = self.window_factory().bring_front(pid, keep_on_top=True)
            valid = (len(current["active"]["paths"]) == 1 and current.get("matchesDatabase")
                and current["active"]["paths"][0]["targetKey"] == target
                and current["active"]["paths"][0].get("monitorDevicePath") == identity
                and self.renderer.pid() == pid and state.get("display", {}).get("hdr") is True
                and all(state.get("presentation", {}).get(k) is True for k in ("presented", "resourcesValid"))
                and window.get("unobstructed") is True)
            if mode == "active":
                reading = self.read_input()
                valid = (valid and reading.get("ok") is True and reading.get("targetKey") == target
                    and reading.get("monitorDevicePath") == identity
                    and type(reading.get("currentValue")) is int and reading.get("currentValue") == expected)
            now = time.monotonic()
            stable_since = (now if stable_since is None else stable_since) if valid else None
            remaining = duration if stable_since is None else max(0, duration - (now - stable_since))
            with self.lock:
                self.data["operation"]["waitRemainingSeconds"] = round(remaining, 1)
            if valid and remaining <= 0 and now <= deadline:
                operation["stableSeconds"] = now - stable_since if mode == "active" else 0
                return reading
            time.sleep(min(.5, max(0, deadline - now)))
        raise TimeoutError("Input did not remain ready throughout the required stability period.")

    def writable_settings(self, settings):
        schema = self.renderer.catalog().get("settingSchema")
        if not isinstance(schema, dict):
            raise RuntimeError("Host setting ranges are unavailable; settings cannot be restored.")
        result = {}
        for name, value in settings.items():
            field = schema.get(name, {})
            if type(value) in (int, float) and (not math.isfinite(value)
                    or value < field.get("minimum", -math.inf) or value > field.get("maximum", math.inf)):
                continue
            result[name] = value
        return result

    def work(self, request):
        operation = dict(self.data["operation"])
        manual = request.get("verificationMode", "ddc") == "manual"
        mode = request.get("switchMode", "pair")
        try:
            controller = self.controller_factory()
            target, identity = request["targetKey"], request["monitorDevicePath"]
            current = controller.inspect()
            if len(current["active"]["paths"]) != 1 or not current.get("matchesDatabase"):
                raise ValueError("Verify exactly one active display and its saved configuration before switching.")
            original_input = self.read_input()
            active = current["active"]["paths"][0]
            if original_input.get("identityMismatch") is True:
                raise ValueError(original_input.get("error") or "Native display identity could not be verified.")
            if (original_input.get("ok") is True and
                    (original_input.get("targetKey") != active["targetKey"]
                     or original_input.get("monitorDevicePath") != active.get("monitorDevicePath"))):
                raise ValueError("DDC/CI display identity does not match the active output.")
            if not manual and (not original_input.get("ok") or type(original_input.get("currentValue")) is not int
                    or not 1 <= original_input["currentValue"] <= 255
                    or original_input.get("targetKey") != active["targetKey"]
                    or original_input.get("monitorDevicePath") != active.get("monitorDevicePath")):
                raise ValueError("DUT DDC/CI input is unavailable; no port switch was applied.")

            selected = next((path for path in controller.api.query(QDC_ALL_PATHS).paths
                             if path.target.available and key(path.target) == target), None)
            if selected is None or controller.api.device_path(selected) != identity:
                raise ValueError("Requested display identity does not match the connected output.")
            if active["targetKey"] == target and active.get("monitorDevicePath") != identity:
                raise ValueError("Active target identity does not match the requested path.")
            if mode == "active" and active["targetKey"] == target:
                raise ValueError("Active switching requires a different input for write verification.")
            preserve = mode in ("active", "passive") and not request["calibration"]
            original_state = self.renderer.state() if preserve else None
            if original_state is not None:
                original_state["settings"] = self.writable_settings(original_state["settings"])
            if not preserve:
                self.renderer.request("set_state", test="StartOfTest", settings={"fullscreen": True})
            if mode == "active":
                operation["write"] = self.input_writer(active["targetKey"], active["monitorDevicePath"], request["expectedInput"])
            if active["targetKey"] != target:
                operation["selection"] = controller.trial(target, identity, None, save_to_database=True)
                operation["portRestart"] = self.renderer.restart()
            hdr = self.hdr_factory().enable(target, identity)
            if hdr.get("changed"):
                operation["hdrRestart"] = self.renderer.restart()
            elif active["targetKey"] == target:
                operation["freshRestart"] = self.renderer.restart()
            if manual:
                reading = {"ok": False, "currentValue": None,
                           "error": "Passive waiting does not verify the DUT input source." if mode == "passive"
                           else "Input source requires manual confirmation."}
            else:
                excluded = original_input["currentValue"] if request["calibration"] and active["targetKey"] != target else None
                reading, samples = self.wait_input(target, identity, request["expectedInput"], excluded=excluded)
                operation["inputSamples"] = samples
            current = controller.inspect()
            if (len(current["active"]["paths"]) != 1 or current["active"]["paths"][0]["targetKey"] != target
                    or current["active"]["paths"][0].get("monitorDevicePath") != identity or not current.get("matchesDatabase")):
                raise RuntimeError("The selected display configuration changed.")
            active_target = target
            fields = {"settings": {"fullscreen": True, "textVisible": False}}
            if original_state is not None:
                fields.update(test=original_state["test"]["id"], settings={**self.writable_settings(original_state["settings"]),
                              "fullscreen": True, "textVisible": False})
            state = self.renderer.request("set_state", **fields)
            if request["command"] == "switch_display_port" and not state.get("display", {}).get("hdr"):
                raise RuntimeError("HDR mode was not confirmed after the port switch.")
            if not all(state.get("presentation", {}).get(k) is True for k in ("presented", "resourcesValid")):
                raise RuntimeError("Host window presentation was not confirmed.")
            window = self.window_factory().bring_front(self.renderer.pid(), keep_on_top=True)
            if not window.get("unobstructed"):
                raise RuntimeError("Host window is obscured or window status could not be verified.")
            if mode in ("active", "passive"):
                reading = self.wait_ready(controller, target, identity, request["expectedInput"], operation, mode, reading)
            with self.lock:
                self.data.update(input=reading, activeTargetKey=active_target, operation=operation,
                                 supported=not manual, manualSupported=True, error="")
                operation.update(phase="ready", ready=True, error="", inputValue=reading.get("currentValue"),
                                 hdr=bool(state["display"]["hdr"]), state=state, window=window, inputVerified=not manual,
                                 timedReady=mode == "passive", waitRemainingSeconds=0)
                for item in self.data["targets"]:
                    item["active"] = item["targetKey"] == self.data["activeTargetKey"]
        except Exception as error:
            with self.lock:
                if getattr(error, "report", None):
                    operation["selection"] = error.report
                if getattr(error, "input_samples", None):
                    operation["inputSamples"] = error.input_samples
                    self.data["input"] = error.last_input
                    reading = error.last_input
                    value = reading.get("currentValue")
                    operation["inputUnavailable"] = (reading.get("identityMismatch") is not True and
                        (reading.get("ok") is not True or type(value) is not int or not 1 <= value <= 255))
                self.data["operation"] = operation
                self.data["operation"].update(phase="failed", ready=False, error=str(error))
