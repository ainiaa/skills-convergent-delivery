import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import delivery_engine as engine_module


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

    def tdd_root(self, directory, name, content):
        root = Path(directory) / "tdd"
        path = root / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return root, path

    def select_with_trusted_adapter(self, root, provider):
        fingerprint = next(
            item[2] for item in engine_module.ADAPTED_TDD_PROVIDERS if item[0] == provider
        )
        with patch.object(engine_module, "file_fingerprint", return_value=fingerprint):
            return engine_module.selection(
                "auto", str(Path(root) / "missing-pdlc"), [root], "feature"
            )

    def test_auto_uses_pdlc_when_capability_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_engine("--pdlc-root", str(self.pdlc_root(directory)))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pdlc-v1", json.loads(result.stdout)["engine"])

    def test_auto_prefers_pdlc_over_an_adapted_tdd_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            pdlc_root = self.pdlc_root(directory)
            tdd_root, _ = self.tdd_root(
                directory,
                "test-driven-development",
                "Write the test first. Follow red-green-refactor.",
            )
            result = self.run_engine(
                "--pdlc-root", str(pdlc_root), "--tdd-root", str(tdd_root)
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pdlc-v1", json.loads(result.stdout)["engine"])

    def test_auto_falls_back_to_native_when_pdlc_is_absent(self):
        result = self.run_engine()

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("native-v1", payload["engine"])
        self.assertIn("fell back", payload["reason"])

    def test_auto_prefers_adapted_superpowers_tdd_after_pdlc(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.tdd_root(
                directory,
                "test-driven-development",
                "Write the test first. Follow red-green-refactor.",
            )
            payload = self.select_with_trusted_adapter(root, "superpowers-tdd-v1")

        self.assertEqual("superpowers-tdd-v1", payload["engine"])
        self.assertEqual(str(path.resolve()), payload["tdd_skill_path"])

    def test_auto_prefers_superpowers_over_mattpocock(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.tdd_root(
                directory,
                "test-driven-development",
                "Write the test first. Follow red-green-refactor.",
            )
            self.tdd_root(
                directory,
                "tdd",
                "Use vertical slices through public APIs.",
            )
            payload = self.select_with_trusted_adapter(root, "superpowers-tdd-v1")

        self.assertEqual("superpowers-tdd-v1", payload["engine"])

    def test_auto_uses_adapted_mattpocock_tdd_when_superpowers_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.tdd_root(
                directory,
                "tdd",
                "Use vertical slices through public APIs.",
            )
            payload = self.select_with_trusted_adapter(root, "mattpocock-tdd-v1")

        self.assertEqual("mattpocock-tdd-v1", payload["engine"])
        self.assertEqual(str(path.resolve()), payload["tdd_skill_path"])

    def test_auto_rejects_a_false_superpowers_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.tdd_root(
                directory,
                "test-driven-development",
                "Write the test first. Follow red-green-refactor. Publish and delete files.",
            )
            result = self.run_engine("--tdd-root", str(root))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("native-v1", json.loads(result.stdout)["engine"])

    def test_auto_uses_a_compatible_generic_tdd_skill_after_adapted_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.tdd_root(
                directory,
                "project-tdd",
                "Run a test first, then use the red and green cycle.",
            )
            result = self.run_engine("--tdd-root", str(root))

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("generic-tdd-v1", payload["engine"])
        self.assertEqual(str(path.resolve()), payload["tdd_skill_path"])

    def test_auto_rejects_a_generic_tdd_orchestrator(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.tdd_root(
                directory,
                "tdd-orchestrator",
                "Run a test first, then use the red and green cycle.",
            )
            result = self.run_engine("--tdd-root", str(root))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("native-v1", json.loads(result.stdout)["engine"])

    def test_auto_rejects_a_generic_tdd_skill_that_declares_unsafe_control_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.tdd_root(
                directory,
                "project-tdd",
                "Run a test first, then use red and green. Publish, delete files, and retry loop.",
            )
            result = self.run_engine("--tdd-root", str(root))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("native-v1", json.loads(result.stdout)["engine"])

    def test_explicit_native_skips_third_party_tdd_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.tdd_root(
                directory,
                "test-driven-development",
                "Write the test first. Follow red-green-refactor.",
            )
            result = self.run_engine("--mode", "native", "--tdd-root", str(root))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("native-v1", json.loads(result.stdout)["engine"])

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

    def test_active_pdlc_task_blocks_when_the_frozen_root_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.pdlc_root(directory)
            replacement = Path(directory) / "replacement"
            for skill in REQUIRED:
                path = replacement / "skills" / skill / "SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("replacement\n", encoding="utf-8")
            initial = self.run_engine("--pdlc-root", str(original))
            payload = json.loads(initial.stdout)
            result = self.run_engine(
                "--previous-engine",
                "pdlc-v1",
                "--previous-pdlc-root",
                str(replacement),
                "--previous-pdlc-fingerprint",
                payload["pdlc_fingerprint"],
            )

        self.assertEqual(2, result.returncode)
        self.assertEqual("blocked", json.loads(result.stdout)["status"])

    def test_active_native_task_stays_native_when_pdlc_appears(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_engine(
                "--pdlc-root", str(self.pdlc_root(directory)), "--previous-engine", "native-v1"
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("native-v1", json.loads(result.stdout)["engine"])

    def test_active_third_party_tdd_task_does_not_switch_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.tdd_root(
                directory,
                "project-tdd",
                "Run a test first, then use the red and green cycle.",
            )
            initial = self.run_engine("--tdd-root", str(root))
            fingerprint = json.loads(initial.stdout)["tdd_skill_fingerprint"]
            result = self.run_engine(
                "--tdd-root",
                str(root),
                "--previous-engine",
                "generic-tdd-v1",
                "--previous-tdd-skill",
                str(path),
                "--previous-tdd-fingerprint",
                fingerprint,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("generic-tdd-v1", json.loads(result.stdout)["engine"])

    def test_active_third_party_tdd_task_blocks_when_its_frozen_skill_is_missing(self):
        result = self.run_engine(
            "--previous-engine",
            "generic-tdd-v1",
            "--previous-tdd-skill",
            "/missing/SKILL.md",
            "--previous-tdd-fingerprint",
            "missing",
        )

        self.assertEqual(2, result.returncode)
        self.assertEqual("blocked", json.loads(result.stdout)["status"])

    def test_installed_pdlc_skills_are_accepted_without_a_source_tree_or_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_engine("--pdlc-root", str(self.pdlc_root(directory, installed=True)))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pdlc-v1", json.loads(result.stdout)["engine"])


if __name__ == "__main__":
    unittest.main()
