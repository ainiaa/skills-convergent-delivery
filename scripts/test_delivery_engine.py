import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("delivery_engine.py")
REQUIRED = (
    "pdlc-tdd",
    "pdlc-implement",
    "pdlc-review",
    "pdlc-feature",
    "pdlc-fix",
)


class DeliveryEngineTest(unittest.TestCase):
    def run_engine(self, *arguments, environment=None):
        with tempfile.TemporaryDirectory() as home:
            return subprocess.run(
                [sys.executable, str(SCRIPT), "select", *arguments],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "HOME": home, **(environment or {})},
            )

    def pdlc_root(self, directory, installed=False):
        root = Path(directory) / "pdlc"
        for skill in REQUIRED:
            file = root / (skill if installed else f"skills/{skill}") / "SKILL.md"
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("ok\n", encoding="utf-8")
        return root

    def test_auto_uses_pdlc_when_capability_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_engine("--pdlc-root", str(self.pdlc_root(directory)))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pdlc-v1", json.loads(result.stdout)["engine"])

    def test_auto_falls_back_to_native_when_pdlc_is_absent(self):
        result = self.run_engine()

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("native-v1", payload["engine"])
        self.assertIn("fell back", payload["reason"])

    def test_auto_discovers_pdlc_from_the_configured_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.pdlc_root(directory, installed=True)
            result = self.run_engine(environment={"CONVERGE_PDLC_ROOT": str(root)})

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pdlc-v1", json.loads(result.stdout)["engine"])

    def test_explicit_pdlc_blocks_when_capability_is_absent(self):
        result = self.run_engine("--mode", "pdlc")

        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("blocked", payload["status"])
        self.assertEqual("environment", payload["code"])

    def test_active_pdlc_task_never_silently_falls_back_to_native(self):
        result = self.run_engine("--previous-engine", "pdlc-v1")

        self.assertEqual(2, result.returncode)
        self.assertEqual("blocked", json.loads(result.stdout)["status"])

    def test_active_native_task_stays_native_when_pdlc_appears(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_engine(
                "--pdlc-root", str(self.pdlc_root(directory)), "--previous-engine", "native-v1"
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("native-v1", json.loads(result.stdout)["engine"])

    def test_installed_pdlc_skills_are_accepted_without_a_source_tree_or_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_engine("--pdlc-root", str(self.pdlc_root(directory, installed=True)))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pdlc-v1", json.loads(result.stdout)["engine"])


if __name__ == "__main__":
    unittest.main()
