"""Compare paired offscreen renders against the untouched upstream source."""
from pathlib import Path
import os
import re
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
BASELINE = "68cda1f04eb14dea882dd9309d50f61803413574"


def functions(source, prefix):
    result = {}
    starts = list(re.finditer(r"(?:void|bool|float|int) Game::(\w+)\b", source))
    for i, match in enumerate(starts):
        if match[1].startswith(prefix):
            end = starts[i + 1].start() if i + 1 < len(starts) else len(source)
            result.setdefault(match[1], []).append(source[match.start():end])
    return result


class RegressionTests(unittest.TestCase):
    def test_existing_pattern_and_keyboard_logic_is_unchanged(self):
        for file in ("ColorSpaces.h", "BasicMath.h", "StepTimer.h"):
            original = subprocess.check_output(["git", "show", f"{BASELINE}:{file}"], cwd=REPO)
            self.assertEqual(original.replace(b"\r\n", b"\n"), (REPO / file).read_bytes().replace(b"\r\n", b"\n"), file)
        original = subprocess.check_output(["git", "show", f"{BASELINE}:Game.cpp"], cwd=REPO).decode("cp1252").replace("\r\n", "\n")
        # Only the known display literals changed to equivalent Unicode escapes.
        original = original.replace("Copyright \u00a9 VESA", r"Copyright \u00A9 VESA")
        original = original.replace("Portrait X-Rite\u2122 color technology", r"Portrait X-Rite\u2122 color technology")
        original = original.replace("1.2.5 X-Rite\u2122 Colors", r"1.2.5 X-Rite\u2122 Colors")
        current = (REPO / "Game.cpp").read_bytes().decode("cp1252").replace("\r\n", "\n")
        for prefix in ("GenerateTestPattern_", "ChangeSubtest", "ChangeCheckerboard", "Toggle", "PauseAnimation", "SetMetadata"):
            self.assertEqual(functions(original, prefix), functions(current, prefix), prefix)
        original_main = subprocess.check_output(["git", "show", f"{BASELINE}:Main.cpp"], cwd=REPO)
        current_main = (REPO / "Main.cpp").read_bytes()
        boundary = b"// Windows procedure"
        self.assertEqual(original_main[original_main.index(boundary):].replace(b"\r\n", b"\n"),
                         current_main[current_main.index(boundary):].replace(b"\r\n", b"\n"))

    def test_paired_hdr_and_sdr_images_and_metadata(self):
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
            outputs = []
            for variant, command in (("baseline", "--capture"), ("automation", "--capture"), ("automation", "--capture-api")):
                binary = root / f"{variant}-x64-Release/harness/bin/RuntimeHarness.exe"
                result = subprocess.run([str(binary), command], cwd=binary.parent, capture_output=True,
                                        env=environment, startupinfo=startup, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                rows = [line.split() for line in result.stdout.decode().splitlines()]
                self.assertGreater(len(rows), 150)
                outputs.append(rows)
            for index in (1, 2):
                with self.subTest(mode=mode, api=index == 2):
                    differences = [(a, b) for a, b in zip(outputs[0], outputs[index]) if a != b]
                    self.assertEqual(len(outputs[0]), len(outputs[index]))
                    self.assertEqual(differences, [])
            reports.append(f"{mode}: {len(outputs[0])} paired renders match (API disabled and enabled).")
        report = REPO / "build-output" / "render-regression-results.txt"
        report.write_text("\n".join(reports) + "\n", encoding="utf-8")
        print("\n".join(reports))


if __name__ == "__main__":
    unittest.main(verbosity=2)
