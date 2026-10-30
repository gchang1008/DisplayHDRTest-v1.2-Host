"""Manual display-port operations outside the official measurement sequence."""
import ctypes as C
import hashlib
import json
import subprocess
import threading
import winreg

from displayhdr_display_paths import (DisplayPaths, Header, TargetName, QDC_ALL_PATHS,
                                      QDC_ONLY_ACTIVE_PATHS, key)
from displayhdr_hdr_control import HdrControl
from displayhdr_monitor_input import InputIdentityError, probe_native, write_native
from displayhdr_window_presentation import WindowPresentation
from displayhdr_edid import read_edid


COMMANDS = {"get_display_ports", "get_display_port_status", "set_display_output",
            "write_display_input", "enable_display_hdr", "present_display_window", "get_display_edid"}


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

    def restart_supported(self):
        return bool(self.server.supervisor and self.server.supervisor.status().get("restartSupported"))

    def pid(self):
        return self.server.supervisor.status()["pid"] if self.server.supervisor else self.server.pid


class DisplayPortService:
    def __init__(self, renderer, controller_factory=DisplayPaths,
                 input_reader=probe_native, hdr_factory=HdrControl, window_factory=WindowPresentation,
                 input_writer=write_native, edid_reader=read_edid):
        self.renderer = renderer
        self.controller_factory, self.input_reader = controller_factory, input_reader
        self.hdr_factory, self.window_factory = hdr_factory, window_factory
        self.input_writer = input_writer
        self.edid_reader = edid_reader
        self.switch_mode = "pair"
        self.skip_ddc = False
        self.lock = threading.RLock()
        self.closed = False
        self.data = {"supported": False, "manualSupported": False, "outputSelectionSupported": False, "targets": [], "activeTargetKey": "", "input": {},
                     "pendingRestore": False, "operation": self.operation()}
        self.seen = set()
        self.running = False
        self.replies = {}

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
                ("supported", "manualSupported", "outputSelectionSupported", "targets", "activeTargetKey", "input", "pendingRestore")}))
            result["switchModes"] = ["active", "passive"]
            result["controlOwner"] = "client"
            result["operation"] = {name: value for name, value in self.data["operation"].items()
                if name in {*self.operation(), "state", "window"}}
            if self.data.get("error"):
                result["error"] = self.data["error"]
            return result

    def busy(self):
        with self.lock:
            return self.running

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
            configuration = controller.inspect()
            selection_supported = (self.renderer.restart_supported() and bool(active_keys)
                                   and active_keys.issubset(targets) and bool(configuration.get("matchesDatabase"))
                                   and all(t["monitorDevicePath"] for t in targets.values()))
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
            elif not configuration.get("matchesDatabase"):
                error = "Active and saved display configurations differ; verify Windows display settings."
            manual_supported = not error
            if self.switch_mode != "passive" and not error and (not reading.get("ok") or type(reading.get("currentValue")) is not int
                              or not 1 <= reading["currentValue"] <= 255):
                error = reading.get("error") or "DUT input value could not be confirmed."
            self.data.update(targets=list(targets.values()), input=reading,
                             activeTargetKey=next(iter(active_keys)) if len(active_keys) == 1 else "",
                             supported=not error, manualSupported=manual_supported,
                             outputSelectionSupported=bool(selection_supported), error=error)
            if self.data["supported"] and self.data["operation"]["phase"] == "failed":
                self.data["operation"] = self.operation()
            return self.status()

    def dispatch(self, request):
        if self.closed:
            raise ValueError("The display-port service has closed.")
        command = request["command"]
        common = {"version", "id", "command"}
        query = command in ("get_display_ports", "get_display_port_status")
        expected = common | ({"switchMode"} if "switchMode" in request else set()) if query else common | {
            "allowInterrupt", "targetKey", "monitorDevicePath"}
        if command == "get_display_edid":
            expected.remove("allowInterrupt")
        if command == "write_display_input":
            expected.add("value")
        if command not in COMMANDS or set(request) != expected or type(request.get("version")) is not int or request["version"] != 1 or not isinstance(request.get("id"), str) or not request["id"]:
            raise ValueError("Unexpected or missing display operation fields.")
        mode = request.get("switchMode", "pair")
        if mode not in ("pair", "active", "passive"):
            raise ValueError("Unknown inventory mode.")
        if query:
            return self.inventory(mode) if command == "get_display_ports" else self.status()
        if command != "get_display_edid" and request["allowInterrupt"] is not True:
            raise ValueError("Explicit allowInterrupt=true is required.")
        if not all(isinstance(request[k], str) and request[k] for k in ("targetKey", "monitorDevicePath")):
            raise ValueError("A display endpoint and device identity are required.")
        if command == "write_display_input" and (type(request["value"]) is not int or not 1 <= request["value"] <= 255):
            raise ValueError("Invalid DDC/CI source value.")
        with self.lock:
            identifier = request["id"]
            if identifier in self.replies:
                previous, result = self.replies[identifier]
                if previous != request:
                    raise ValueError("Request id belongs to a different operation.")
                return result
            if identifier in self.seen:
                raise ValueError("Request already attempted; no command was repeated.")
            if self.busy():
                raise ValueError("A display operation is running.")
            self.seen.add(identifier)
            self.running = True
            try:
                if command == "set_display_output" and not self.renderer.restart_supported():
                    raise ValueError("Output selection requires a managed Host launcher.")
                controller = self.controller_factory()
                current = controller.inspect()
                active = current["active"]["paths"]
                if not active or not current.get("matchesDatabase"):
                    raise ValueError("Active output and matching Windows configuration are required.")
                if command != "set_display_output" and len(active) != 1:
                    raise ValueError("Exactly one active output is required for this operation.")
                target, identity = request["targetKey"], request["monitorDevicePath"]
                selected = next((p for p in controller.api.query(QDC_ALL_PATHS).paths
                                 if p.target.available and key(p.target) == target), None)
                if selected is None or controller.api.device_path(selected) != identity:
                    raise ValueError("Requested display identity does not match the connected output.")
                if command != "set_display_output" and (active[0]["targetKey"] != target or active[0].get("monitorDevicePath") != identity):
                    raise ValueError("Operation requires the requested active display identity.")
                if command == "get_display_edid":
                    result = self.edid_reader(identity)
                    after = controller.inspect()["active"]["paths"]
                    if (len(after) != 1 or after[0]["targetKey"] != target
                            or after[0].get("monitorDevicePath") != identity):
                        raise ValueError("Active display identity changed during EDID reading.")
                elif command == "set_display_output":
                    changed = len(active) != 1 or active[0]["targetKey"] != target
                    result = {"changed": changed}
                    if changed:
                        result["selection"] = controller.trial(target, identity, None, save_to_database=True)
                elif command == "write_display_input":
                    result = self.input_writer(target, identity, request["value"])
                elif command == "enable_display_hdr":
                    result = self.hdr_factory().enable(target, identity)
                else:
                    result = self.window_factory().bring_front(self.renderer.pid(), keep_on_top=True)
                result = {"command": command, "targetKey": target, "monitorDevicePath": identity, **result}
                self.replies[identifier] = (dict(request), result)
                return result
            finally:
                self.running = False
