import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class CheckScriptTest(unittest.TestCase):
    def test_project_check_passes(self):
        result = subprocess.run(
            ["bash", "scripts/check.sh"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        for skill in ("converge", "converge-plan", "converge-review", "converge-batch"):
            self.assertIn(f"Official validator passed: {skill}", result.stdout)
        self.assertIn("All checks passed.", result.stdout)


if __name__ == "__main__":
    unittest.main()
