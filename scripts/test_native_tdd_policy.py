import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("native_tdd_policy.py")
SPEC = importlib.util.spec_from_file_location("native_tdd_policy", MODULE_PATH)
native_tdd_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_tdd_policy)


class NativeTddPolicyTest(unittest.TestCase):
    def test_coverage_command_has_priority_and_is_split_into_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: python3 -m pytest --cov --cov-fail-under=91\n", encoding="utf-8"
            )
            (standard / "quality-targets.yml").write_text("coverage: 92\n", encoding="utf-8")

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("test-commands.yml", policy["source"])
        self.assertEqual(91, policy["threshold"])
        self.assertEqual("argv", policy["threshold_source"])
        self.assertEqual(["python3", "-m", "pytest", "--cov", "--cov-fail-under=91"], policy["argv"])

    def test_quality_target_overrides_the_default_when_no_command_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "quality-targets.yml").write_text("coverage: 92\n", encoding="utf-8")

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("quality-targets.yml", policy["source"])
        self.assertEqual(92, policy["threshold"])
        self.assertEqual("quality-targets.yml", policy["threshold_source"])
        self.assertIsNone(policy["argv"])

    def test_no_project_configuration_uses_the_85_percent_default(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = native_tdd_policy.resolve(Path(directory))

        self.assertEqual("default", policy["source"])
        self.assertEqual(85, policy["threshold"])
        self.assertEqual("default", policy["threshold_source"])
        self.assertIsNone(policy["argv"])

    def test_shell_syntax_is_not_treated_as_an_executable_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: pytest --cov | tee coverage.log\n", encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])
        self.assertIn("shell syntax", policy["reason"])


if __name__ == "__main__":
    unittest.main()
