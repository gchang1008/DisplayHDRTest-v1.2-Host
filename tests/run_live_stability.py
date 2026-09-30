"""Five-minute mixed API control/query/reconnect run against the production executable."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from displayhdr_api import DisplayHDRClient
from run_live_benchmark import resources, OUT

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
binary = Path(__file__).resolve().parents[2] / "build-output/automation-x64-Release/DisplayHDRComplianceTests.exe"
startup = subprocess.STARTUPINFO()
startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 1
process = subprocess.Popen([str(binary), "--api"], cwd=binary.parent, startupinfo=startup)
print(f"PID={process.pid}", flush=True)
client = None
samples = []
commands = reconnects = 0
start = time.monotonic()
last_frame = last_version = 0
try:
    client = DisplayHDRClient(process.pid)
    patterns = client.request("catalog")["catalog"]["tests"]
    while time.monotonic() - start < 300:
        assert process.poll() is None, "Production process exited unexpectedly"
        if commands % 10 == 0:
            target = patterns[(commands // 10) % len(patterns)]["id"]
            identifier = f"stability-{commands}"
            response = client.request("set_state", id=identifier, test=target,
                                      settings={"textVisible": False, "xriteAuto": False,
                                                "color": ("Red", "Green", "Blue", "White")[(commands // 10) % 4]})
            assert response["ok"], response
            state = response["state"]
            assert state["test"]["id"] == target and state["lastSetRequestId"] == identifier
        else:
            response = client.request("get_state")
            assert response["ok"], response
            state = response["state"]
        assert state["presentation"]["submitted"] and state["presentation"]["resourcesValid"], state
        assert state["presentation"]["frameId"] >= last_frame
        assert state["stateVersion"] >= last_version
        last_frame = state["presentation"]["frameId"]
        last_version = state["stateVersion"]
        commands += 1
        if commands % 100 == 0:
            client.close()
            client = DisplayHDRClient(process.pid)
            reconnects += 1
        elapsed = time.monotonic() - start
        if not samples or elapsed - samples[-1]["seconds"] >= 15:
            _, private = resources(process)
            handles = ctypes.c_ulong()
            assert kernel.GetProcessHandleCount(int(process._handle), ctypes.byref(handles))
            sample = dict(seconds=elapsed, privateBytes=private, handles=handles.value, commands=commands)
            samples.append(sample)
            print(json.dumps(sample), flush=True)
            (OUT / "stability-samples.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
    warmed = [s for s in samples if s["seconds"] >= 60]
    result = dict(passed=False, seconds=time.monotonic() - start, commands=commands, reconnects=reconnects,
                  maxPrivateVariationBytes=max(s["privateBytes"] for s in warmed) - min(s["privateBytes"] for s in warmed),
                  maxHandleVariation=max(s["handles"] for s in warmed) - min(s["handles"] for s in warmed))
    result["passed"] = result["maxPrivateVariationBytes"] < 20 * 1024 * 1024 and result["maxHandleVariation"] <= 5
    (OUT / "stability-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    assert result["passed"], "Stability thresholds exceeded; inspect stored samples"
finally:
    if client:
        client.close()
    # The UI acceptance step closes this dedicated process through its actual window.
    print(f"CLOSE_PID={process.pid}", flush=True)
