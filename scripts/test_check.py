import os
import subprocess
import tempfile
import yaml
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class CheckScriptTest(unittest.TestCase):
    def test_ci_prepares_a_pinned_validator_and_passes_it_to_the_gate(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        steps = workflow["jobs"]["verify"]["steps"]
        gate_index = next(i for i, step in enumerate(steps) if step.get("run") == "bash scripts/check.sh --full")
        gate = steps[gate_index]
        self.assertEqual("${{ runner.temp }}/quick_validate.py", gate.get("env", {}).get("CONVERGE_QUICK_VALIDATE"))
        setup = next(step["run"] for step in steps[:gate_index] if "quick_validate.py" in step.get("run", ""))
        self.assertRegex(setup, r"openai/skills/[0-9a-f]{40}/")
        self.assertIn("sha256sum --check", setup)

    def test_missing_validator_fails_before_the_suite_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["bash", "scripts/check.sh", "--full"], cwd=ROOT,
                                    env={**os.environ, "CONVERGE_QUICK_VALIDATE": str(Path(directory) / "missing.py")},
                                    capture_output=True, text=True, check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Official Skill validator missing", result.stderr)
        self.assertNotIn("All checks passed", result.stdout)

    def test_ci_runs_the_full_release_gate_without_a_fixed_python_minor(self):
        check = (ROOT / "scripts/check.sh").read_text(encoding="utf-8")
        workflow = ROOT / ".github/workflows/ci.yml"

        self.assertNotIn("--python 3.13", check)
        self.assertTrue(workflow.is_file())
        content = workflow.read_text(encoding="utf-8")
        self.assertIn("pull_request:", content)
        self.assertIn('\"v*\"', content)
        self.assertIn("bash scripts/check.sh --full", content)
        self.assertIn("scripts/test_multi_model_repo_eval.py", check)

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
