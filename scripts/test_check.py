import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class CheckScriptTest(unittest.TestCase):
    def test_runtime_lock_files_are_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True
        )

        self.assertFalse([
            path for path in result.stdout.splitlines()
            if path.endswith(".json.lock") and (ROOT / path).exists()
        ])

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
        self.assertIn("Full autonomous trajectory skipped", result.stdout)
        self.assertIn("All checks passed.", result.stdout)


if __name__ == "__main__":
    unittest.main()
