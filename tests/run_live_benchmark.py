"""Compare identically instrumented, visible hardware builds; no rendering replacements."""
import csv
import ctypes
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from displayhdr_api import DisplayHDRClient

OUT = Path(__file__).resolve().parents[2] / "build-output" / "behavior-verification"
OUT.mkdir(exist_ok=True)
ROOT = Path(os.environ["LOCALAPPDATA"]) / "DisplayHDRAutomationBuild"
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
psapi = ctypes.WinDLL("psapi", use_last_error=True)


class Memory(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
        (key, ctypes.c_size_t) for key in ("peakWorking", "working", "peakPaged", "paged", "peakNonpaged", "nonpaged", "pagefile", "peakPagefile", "private")]


psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), ctypes.c_ulong]


def resources(process):
    values = [ctypes.c_ulonglong() for _ in range(4)]
    if not kernel.GetProcessTimes(int(process._handle), *(ctypes.byref(v) for v in values)):
        raise ctypes.WinError(ctypes.get_last_error())
    memory = Memory()
    memory.cb = ctypes.sizeof(memory)
    if not psapi.GetProcessMemoryInfo(int(process._handle), ctypes.byref(memory), memory.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return (values[2].value + values[3].value) / 1e7, memory.private


def percentile(values, quantile):
    return sorted(values)[int((len(values) - 1) * quantile)]


def run(variant, mode, pattern, repeat, duration=20):
    label = f"{variant}-{mode}-{pattern}-{repeat}"
    binary = ROOT / f"{variant}-x64-Release/behavior-probe/bin/DisplayHDRComplianceTests.exe"
    environment = os.environ.copy()
    environment.update(DISPLAYHDR_PROBE_LOG=str(OUT / f"{label}.csv"), DISPLAYHDR_PROBE_SECONDS=str(duration),
                       DISPLAYHDR_PROBE_PATTERN=str(pattern))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1
    process = subprocess.Popen([str(binary)] + (["--api"] if mode in ("idle", "query") else []),
                               cwd=binary.parent, env=environment, startupinfo=startup)
    requests = 0
    latencies = []
    samples = []
    client = None
    started = time.monotonic()
    try:
        if mode == "query":
            client = DisplayHDRClient(process.pid)
        while process.poll() is None:
            if time.monotonic() - started > duration + 15:
                raise TimeoutError(f"{label} did not exit normally")
            if client:
                before = time.perf_counter()
                try:
                    response = client.request("get_state")
                except (OSError, ConnectionError):
                    if process.wait(2) == 0:
                        break
                    raise
                latencies.append((time.perf_counter() - before) * 1000)
                assert response["ok"] and response["state"]["presentation"]["submitted"], response
                requests += 1
            else:
                time.sleep(.05)
            if not samples or time.monotonic() - samples[-1][0] >= 1:
                cpu, private = resources(process)
                samples.append((time.monotonic(), cpu, private))
        assert process.returncode == 0, (label, process.returncode)
    finally:
        if client:
            client.close()
        if process.poll() is None:
            process.terminate()
            process.wait(10)
    rows = list(csv.DictReader((OUT / f"{label}.csv").open()))
    rows = [r for r in rows if float(r["qpc"]) - float(rows[0]["qpc"]) > 2]
    periods = [(float(b["qpc"]) - float(a["qpc"])) * 1000 for a, b in zip(rows, rows[1:])]
    assert len(periods) > 100, label
    sampled = samples[2:]
    cpu = (sampled[-1][1] - sampled[0][1]) / (sampled[-1][0] - sampled[0][0])
    result = dict(label=label, frames=len(rows), medianMs=statistics.median(periods), p95Ms=percentile(periods, .95),
                  p99Ms=percentile(periods, .99), cpuCores=cpu, privateBytes=samples[-1][2],
                  memoryGrowthBytes=samples[-1][2] - sampled[0][2], queries=requests,
                  queryP95Ms=percentile(latencies, .95) if latencies else None,
                  slowFrameFraction=sum(p > 2 * statistics.median(periods) for p in periods) / len(periods))
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    results = []
    for repeat in range(2):
        for pattern in (8, 25):  # FlashTest / SubTitleFlicker (verify ids against Game.h)
            variants = [("baseline", "off"), ("automation", "off"), ("automation", "idle"), ("automation", "query")]
            if repeat:
                variants.reverse()
            for variant, mode in variants:
                results.append(run(variant, mode, pattern, repeat))
                (OUT / "benchmark-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    comparisons = []
    for pattern in (8, 25):
        base = [r for r in results if r["label"].startswith(f"baseline-off-{pattern}-")]
        for mode in ("off", "idle", "query"):
            current = [r for r in results if r["label"].startswith(f"automation-{mode}-{pattern}-")]
            metrics = {}
            for key in ("medianMs", "p95Ms", "slowFrameFraction", "cpuCores"):
                metrics[key] = statistics.median(r[key] for r in current) - statistics.median(r[key] for r in base)
            passed = (metrics["medianMs"] <= 1 and metrics["p95Ms"] <= 2
                      and metrics["slowFrameFraction"] <= .01 and metrics["cpuCores"] <= .1)
            comparisons.append(dict(pattern=pattern, mode=mode, difference=metrics, passed=passed))
    (OUT / "benchmark-comparisons.json").write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    print(json.dumps(comparisons, indent=2), flush=True)
    if not all(c["passed"] for c in comparisons):
        raise SystemExit(1)
