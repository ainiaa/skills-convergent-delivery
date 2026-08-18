import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("delivery_task_key.py")


class DeliveryTaskKeyTest(unittest.TestCase):
    def run_key(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_equivalent_scope_has_a_stable_key(self):
        first = self.run_key(
            "--repo", "/repo/common.git",
            "--baseline", "abc123",
            "--acceptance", "Return a paged result",
            "--acceptance", "Reject invalid page numbers",
            "--module", "service",
            "--module", "api",
        )
        second = self.run_key(
            "--repo", "/repo/common.git",
            "--baseline", "abc123",
            "--acceptance", "Reject invalid page numbers",
            "--acceptance", "Return a paged result",
            "--module", "api",
            "--module", "service",
        )

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(first.stdout.startswith("task-"))

    def test_changed_acceptance_has_a_different_key(self):
        first = self.run_key(
            "--repo", "/repo/common.git", "--baseline", "abc123", "--acceptance", "Return a page"
        )
        second = self.run_key(
            "--repo", "/repo/common.git", "--baseline", "abc123", "--acceptance", "Export all rows"
        )

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotEqual(first.stdout, second.stdout)

    def test_empty_acceptance_is_rejected(self):
        result = self.run_key("--repo", "/repo/common.git", "--baseline", "abc123")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("at least one acceptance", result.stderr)


if __name__ == "__main__":
    unittest.main()
