"""Match deterministic updates, dynamic renders and boundary state to upstream."""
from pathlib import Path
import os
import subprocess
import unittest


class TimingRegression(unittest.TestCase):
    def test_paired_dynamic_hdr_and_sdr_sequences(self):
        root = Path(os.environ["LOCALAPPDATA"]) / "DisplayHDRAutomationBuild"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        reports = []
        for mode in ("HDR", "SDR"):
            environment = os.environ.copy()
            environment.pop("DISPLAYHDR_TEST_SDR", None)
            if mode == "SDR":
                environment["DISPLAYHDR_TEST_SDR"] = "1"
            results = []
            for variant, command in (("baseline", "--timing"), ("automation", "--timing"), ("automation", "--timing-api")):
                binary = root / f"{variant}-x64-Release/harness/bin/RuntimeHarness.exe"
                run = subprocess.run([str(binary), command], cwd=binary.parent, env=environment,
                                     capture_output=True, startupinfo=startup, timeout=120)
                self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
                results.append(run.stdout.splitlines())
            self.assertGreater(len(results[0]), 800)
            self.assertEqual(results[0], results[1], mode + " API off")
            self.assertEqual(results[0], results[2], mode + " API on")
            reports.append(f"{mode}: {len(results[0])} dynamic state/pixel snapshots match across three variants.")
        output = Path(__file__).resolve().parents[1] / "build-output/behavior-verification/dynamic-results.txt"
        output.parent.mkdir(exist_ok=True)
        output.write_text("\n".join(reports) + "\n", encoding="utf-8")
        print("\n".join(reports))

    def test_paired_fault_recovery(self):
        root = Path(os.environ["LOCALAPPDATA"]) / "DisplayHDRAutomationBuild"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        for mode in ("HDR", "SDR"):
            environment = os.environ.copy()
            environment.pop("DISPLAYHDR_TEST_SDR", None)
            if mode == "SDR": environment["DISPLAYHDR_TEST_SDR"] = "1"
            results = []
            for variant, command in (("baseline", "--faults"), ("automation", "--faults"), ("automation", "--faults-api")):
                binary = root / f"{variant}-x64-Release/harness/bin/RuntimeHarness.exe"
                run = subprocess.run([str(binary), command], cwd=binary.parent, env=environment,
                                     capture_output=True, startupinfo=startup, timeout=120)
                results.append((run.returncode, run.stdout.splitlines()))
            self.assertEqual(results[0][0], 0xC0000005, "Known baseline fault injection outcome changed")
            self.assertEqual(len(results[0][1]), 20)
            self.assertEqual(results[0], results[1], mode + " API off")
            self.assertEqual(results[0], results[2], mode + " API on")
            for offset in range(0, 18, 6):
                original = results[0][1][offset].split()[1:]
                for index in (2, 4, 5):
                    self.assertEqual(original, results[0][1][offset + index].split()[1:])
            import json
            output = Path(__file__).resolve().parents[1] / "build-output/behavior-verification" / f"fault-{mode}.json"
            output.write_text(json.dumps({"equivalent": True, "recoveryPassed": False,
                "exitCode": results[0][0], "snapshots": [line.decode() for line in results[0][1]],
                "knownIssue": "AnimatedColorGradient after fourth device rebuild: all three variants access violation"}, indent=2), encoding="utf-8")
