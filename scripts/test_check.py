import os
import subprocess
import unittest
from unittest import mock
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

    def test_default_check_validates_only_the_core_suite(self):
        if os.environ.get("CONVERGE_CHECK_SELF_TEST") == "1":
            check = (ROOT / "scripts/check.sh").read_text(encoding="utf-8")
            self.assertIn(
                "CORE_SKILLS=(converge converge-plan converge-review converge-batch converge-eval)",
                check,
            )
            self.assertIn(
                "EXTENSION_SKILLS=(converge-autonomy converge-multimodel)", check,
            )
            self.assertIn("SKILLS=(\"${CORE_SKILLS[@]}\")", check)
            self.assertIn("SKILLS+=(\"${EXTENSION_SKILLS[@]}\")", check)
            self.assertIn(
                "Extension suite skipped; run bash scripts/check.sh --full before release.", check,
            )
            return

        result = subprocess.run(
            ["bash", "scripts/check.sh"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        for skill in (
            "converge", "converge-plan", "converge-review", "converge-batch", "converge-eval",
        ):
            self.assertIn(f"Official validator passed: {skill}", result.stdout)
        for extension in ("converge-autonomy", "converge-multimodel"):
            self.assertNotIn(f"Official validator passed: {extension}", result.stdout)
        self.assertIn("Extension suite skipped; run bash scripts/check.sh --full", result.stdout)
        self.assertIn("Check script self-test passed.", result.stdout)
        self.assertIn("All checks passed.", result.stdout)

    def test_in_check_mode_does_not_reexecute_the_suite(self):
        with mock.patch.object(subprocess, "run") as run:
            with mock.patch.dict(os.environ, {"CONVERGE_CHECK_SELF_TEST": "1"}):
                self.test_default_check_validates_only_the_core_suite()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
