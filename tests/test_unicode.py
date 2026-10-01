"""Check compiled display strings independently of the build locale."""
from pathlib import Path
import unittest


class UnicodeTests(unittest.TestCase):
    def test_release_contains_original_unicode_display_strings(self):
        executable = Path(__file__).resolve().parents[1] / "build-output/automation-x64-Release/DisplayHDRComplianceTests.exe"
        self.assertTrue(executable.is_file(), "Build the x64 Release Host before running this test.")
        binary = executable.read_bytes()
        for text in ("Copyright \u00a9 VESA", "Includes Portrait X-Rite\u2122 color technology",
                     "1.2.5 X-Rite\u2122 Colors"):
            with self.subTest(text=text):
                self.assertIn(text.encode("utf-16-le"), binary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
