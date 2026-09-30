import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POLICY_SCRIPT = ROOT / "scripts/skillopt_policy.py"


class SkillReviewPolicyTest(unittest.TestCase):
    def run_policy(self, config_path, global_config_path):
        return subprocess.run(
            [
                sys.executable,
                str(POLICY_SCRIPT),
                "--config",
                str(config_path),
                "--global-config",
                str(global_config_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_config_disables_weekly_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_policy(root / "project.toml", root / "global.toml")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"action": "skip", "enabled": False}, json.loads(result.stdout))

    def test_global_true_enables_weekly_review_when_project_setting_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            global_config = root / "global.toml"
            global_config.write_text("[skill_review]\nenabled = true\n", encoding="utf-8")
            result = self.run_policy(root / "project.toml", global_config)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"action": "review", "enabled": True}, json.loads(result.stdout))

    def test_global_false_disables_weekly_review_when_project_setting_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            global_config = root / "global.toml"
            global_config.write_text("[skill_review]\nenabled = false\n", encoding="utf-8")
            result = self.run_policy(root / "project.toml", global_config)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"action": "skip", "enabled": False}, json.loads(result.stdout))

    def test_project_true_overrides_global_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_config = root / "project.toml"
            project_config.write_text("[skill_review]\nenabled = true\n", encoding="utf-8")
            global_config = root / "global.toml"
            global_config.write_text("[skill_review]\nenabled = false\n", encoding="utf-8")
            result = self.run_policy(project_config, global_config)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"action": "review", "enabled": True}, json.loads(result.stdout))

    def test_project_false_overrides_global_true(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_config = root / "project.toml"
            project_config.write_text("[skill_review]\nenabled = false\n", encoding="utf-8")
            global_config = root / "global.toml"
            global_config.write_text("[skill_review]\nenabled = true\n", encoding="utf-8")
            result = self.run_policy(project_config, global_config)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"action": "skip", "enabled": False}, json.loads(result.stdout))

    def test_project_without_setting_inherits_global_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_config = root / "project.toml"
            project_config.write_text("[other]\nvalue = true\n", encoding="utf-8")
            global_config = root / "global.toml"
            global_config.write_text("[skill_review]\nenabled = true\n", encoding="utf-8")
            result = self.run_policy(project_config, global_config)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"action": "review", "enabled": True}, json.loads(result.stdout))

    def test_malformed_or_non_boolean_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "project.toml"
            global_config = root / "global.toml"
            global_config.write_text("[skill_review]\nenabled = true\n", encoding="utf-8")
            for contents in (
                "[skill_review\nenabled = true\n",
                "[skill_review]\nenabled = 1\n",
                'skill_review = "invalid table"\n',
            ):
                config.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents):
                    result = self.run_policy(config, global_config)
                    self.assertEqual(2, result.returncode)
                    self.assertIn("skill review policy invalid", result.stderr)
                    self.assertEqual("", result.stdout)

    def test_invalid_global_config_fails_closed_when_project_is_unset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            global_config = root / "global.toml"
            global_config.write_text("[skill_review]\nenabled = 1\n", encoding="utf-8")
            result = self.run_policy(root / "project.toml", global_config)

        self.assertEqual(2, result.returncode)
        self.assertIn("skill_review.enabled must be true or false", result.stderr)
        self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
