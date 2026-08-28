import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from autonomous_delivery_eval import evaluate, evaluate_trusted, validate
from controller_snapshot import create_snapshot
from delivery_state import state_path


CATALOG = Path(__file__).resolve().parent.parent / "references/autonomous-delivery-evaluation.json"


class AutonomousDeliveryEvalTest(unittest.TestCase):
    def managed_snapshot_state(self, directory, descriptor):
        path = state_path(Path(directory) / "state", "/repo/eval.git", "autonomy-eval", "run-1")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "schema_version": 11, "repo_id": "/repo/eval.git", "task_key": "autonomy-eval",
            "run_id": "run-1", "controller": {"snapshot": descriptor},
        }), encoding="utf-8")
        return path

    def test_catalog_covers_the_no_manual_continue_failure_modes_without_transcripts(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(47, len(validate(catalog)))
        self.assertIn("full-fix", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("repeated-finding", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("claude-native-stop", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("codex-no-progress", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-final-audit", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-audit-failure-blocks", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-runner-ledger", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-invalid-state-isolated", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-hook-state-protected", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-wakeup-non-destructive", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("hook-report-only-revision-blocked", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("hook-queue-failure-terminalizes", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-verifier-failure-receipt", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-reaudit-finding-receipt", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("service-non-object-state-visible", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("doctor-non-object-state-visible", [item["id"] for item in catalog["scenarios"]])
        self.assertIn("begin-release-failure-visible", [item["id"] for item in catalog["scenarios"]])

    def test_execute_runs_the_frozen_behavior_checks_without_returning_transcripts(self):
        report = evaluate(json.loads(CATALOG.read_text(encoding="utf-8")), execute=True)

        self.assertEqual("completed", report["status"])
        self.assertFalse(report["transcript_storage"])
        self.assertEqual(47, len(report["results"]))
        for result in report["results"].values():
            self.assertEqual({"status", "duration_ms", "usage", "receipt_fingerprint"}, set(result))
            self.assertEqual("passed", result["status"])

    def test_execute_marks_the_evaluation_failed_when_a_bound_check_fails(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        catalog["scenarios"][0]["check"] = [
            "scripts/test_autonomy_gate.py", "AutonomyMissingTest.test_missing",
        ]

        report = evaluate(catalog, execute=True)

        self.assertEqual("failed", report["status"])
        self.assertEqual("failed", report["results"]["full-fix"]["status"])

    def test_command_exits_nonzero_when_a_bound_check_fails(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        catalog["scenarios"][0]["check"] = [
            "scripts/test_autonomy_gate.py", "AutonomyMissingTest.test_missing",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/autonomous_delivery_eval.py", "--catalog", str(path), "--execute"],
                cwd=CATALOG.parent.parent, text=True, capture_output=True, check=False,
            )

        self.assertEqual(2, result.returncode)
        self.assertEqual("failed", json.loads(result.stdout)["status"])

    def test_trusted_execution_uses_only_a_verified_controller_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = create_snapshot(
                CATALOG.parent.parent, Path(directory) / "control", profile="extended"
            )
            descriptor_path = self.managed_snapshot_state(directory, descriptor)
            result = subprocess.run(
                [
                    sys.executable, str(Path(descriptor["root"]) / "scripts/autonomous_delivery_eval.py"),
                    "--snapshot-descriptor", str(descriptor_path),
                ],
                cwd=CATALOG.parent.parent, text=True, capture_output=True, check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("planned", report["status"])
        self.assertEqual("snapshot", report["trust_level"])
        self.assertEqual(descriptor["protocol_fingerprint"], report["controller_fingerprint"])

    def test_trusted_execution_runs_the_snapshot_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = create_snapshot(
                CATALOG.parent.parent, Path(directory) / "control", profile="extended"
            )
            descriptor_path = self.managed_snapshot_state(directory, descriptor)
            result = subprocess.run(
                [
                    sys.executable, str(Path(descriptor["root"]) / "scripts/autonomous_delivery_eval.py"),
                    "--snapshot-descriptor", str(descriptor_path), "--execute",
                ],
                cwd=CATALOG.parent.parent, text=True, capture_output=True, check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("completed", report["status"])
        self.assertTrue(all(item["status"] == "passed" for item in report["results"].values()))

    def test_trusted_evaluation_rejects_the_mutable_workspace_evaluator(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = create_snapshot(
                CATALOG.parent.parent, Path(directory) / "control", profile="extended"
            )
            descriptor_path = self.managed_snapshot_state(directory, descriptor)

            with self.assertRaisesRegex(ValueError, "trusted snapshot"):
                evaluate_trusted(descriptor_path)

    def test_catalog_rejects_transcript_storage_and_missing_trajectory_coverage(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        catalog["privacy"]["store_transcript"] = True
        with self.assertRaisesRegex(ValueError, "transcript"):
            validate(catalog)
        catalog["privacy"]["store_transcript"] = False
        catalog["scenarios"] = catalog["scenarios"][:14]
        with self.assertRaisesRegex(ValueError, "15"):
            validate(catalog)

    def test_execution_ignores_pythonpath_inherited_from_the_candidate_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            poison = Path(directory) / "poison"
            poison.mkdir()
            (poison / "sitecustomize.py").write_text("raise RuntimeError('poisoned')\n", encoding="utf-8")
            with patch.dict("os.environ", {"PYTHONPATH": str(poison)}):
                report = evaluate(json.loads(CATALOG.read_text(encoding="utf-8")), execute=True)

        self.assertEqual("completed", report["status"])


if __name__ == "__main__":
    unittest.main()
