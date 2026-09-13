#!/usr/bin/env python3
"""Regression tests for minimal nonterminal Converge work-item persistence."""

import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from evidence_contract import run_evidence
from reference_receipt import freeze_receipt
from work_item import (
    allow_verifier_attempt,
    complete_work_item,
    record_verifier_failure,
    resume_or_create,
    run_work_item_evidence,
    work_item_key,
    work_item_path,
)


WORK_ITEM = Path(__file__).with_name("work_item.py")


class WorkItemTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "state"
        self.workspace = Path(self.directory.name) / "workspace"
        self.workspace.mkdir()
        self.reference_receipt = freeze_receipt([])

    def tearDown(self):
        self.directory.cleanup()

    def request(self, **overrides):
        value = {
            "state_root": self.root,
            "workspace": self.workspace,
            "baseline": "a" * 40,
            "target": "status-normalization",
            "requirements": ["normalize missing status"],
            "acceptance": ["missing status normalizes to empty"],
            "decisions": ["None normalizes to empty"],
            "reference_receipt": self.reference_receipt,
            "continuation": True,
        }
        value.update(overrides)
        return resume_or_create(**value)

    @staticmethod
    def evidence(source, argv, receipt_fingerprint, exit_code):
        return {
            "source": {"source_fingerprint": source}, "argv": argv,
            "receipt_fingerprint": receipt_fingerprint, "exit_code": exit_code,
        }

    def test_one_shot_inline_does_not_create_a_work_item(self):
        result = self.request(continuation=False)

        self.assertEqual({"status": "inline", "work_item": None}, result)
        self.assertFalse(self.root.exists())

    def test_rejects_malformed_feature_identity_before_writing(self):
        invalid_requests = (
            {"continuation": "yes"},
            {"baseline": "not-a-commit"},
            {"target": " "},
            {"requirements": []},
            {"acceptance": []},
        )

        for overrides in invalid_requests:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.request(**overrides)
        self.assertFalse(self.root.exists())

    def test_unique_nonterminal_item_is_created_then_resumed(self):
        created = self.request()
        resumed = self.request()

        self.assertEqual("created", created["status"])
        self.assertEqual("resumed", resumed["status"])
        self.assertEqual(created["work_item"], resumed["work_item"])
        self.assertEqual(0o600, Path(created["path"]).stat().st_mode & 0o777)

    def test_legacy_nonterminal_item_without_successes_still_resumes(self):
        created = self.request()
        path = Path(created["path"])
        legacy = json.loads(path.read_text(encoding="utf-8"))
        legacy.pop("verifier_successes")
        path.write_text(json.dumps(legacy), encoding="utf-8")

        resumed = self.request()

        self.assertEqual("resumed", resumed["status"])
        self.assertEqual([], resumed["work_item"]["verifier_successes"])

    def test_different_feature_or_acceptance_never_collides(self):
        first = self.request()
        feature = self.request(target="delivery-retry")
        acceptance = self.request(acceptance=["retry result is observable"])

        self.assertEqual(3, len({first["path"], feature["path"], acceptance["path"]}))

    def test_feature_reference_binding_must_match_the_work_item_target(self):
        reference = "codex://thread/other-feature"
        receipt = freeze_receipt(
            [{"reference": reference, "status": "read", "content_fingerprint": "a" * 64}],
            feature_bindings=[{
                "target": "other-feature", "reference": reference, "relation": "analogy",
                "behaviors": [{
                    "input": "input", "state": "state", "output": "output", "effect": "effect",
                    "caller": "caller", "verifier": "python3 -m unittest",
                }],
            }],
        )

        with self.assertRaisesRegex(ValueError, "feature binding target"):
            self.request(reference_receipt=receipt)

    def test_resume_rejects_a_changed_frozen_decision_or_reference_receipt(self):
        reference = "codex://thread/source-feature"
        first_receipt = freeze_receipt([
            {"reference": reference, "status": "read", "content_fingerprint": "a" * 64},
        ])
        second_receipt = freeze_receipt([
            {"reference": reference, "status": "read", "content_fingerprint": "b" * 64},
        ])
        self.request(reference_receipt=first_receipt)

        with self.assertRaisesRegex(ValueError, "semantic contract differs"):
            self.request(decisions=["None is rejected"], reference_receipt=first_receipt)
        with self.assertRaisesRegex(ValueError, "semantic contract differs"):
            self.request(reference_receipt=second_receipt)

    def test_resume_rejects_a_changed_frozen_baseline(self):
        self.request()

        with self.assertRaisesRegex(ValueError, "baseline differs"):
            self.request(baseline="b" * 40)

    def test_multiple_matching_nonterminal_items_block_instead_of_guessing(self):
        created = self.request()
        duplicate = copy.deepcopy(created["work_item"])
        duplicate["baseline"] = "b" * 40
        duplicate["task_key"] = work_item_key(
            self.workspace, duplicate["baseline"], duplicate["target"],
            duplicate["requirements"], duplicate["acceptance"],
        )
        path = work_item_path(
            self.root, self.workspace, duplicate["baseline"], duplicate["target"],
            duplicate["requirements"], duplicate["acceptance"],
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(duplicate), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.request()

    def test_malformed_stored_item_blocks_resume_instead_of_ignoring_it(self):
        created = self.request()
        Path(created["path"]).write_text("{not json", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "stored work item is invalid"):
            self.request()

    def test_identical_verifier_failure_cannot_be_attempted_again_without_new_evidence(self):
        created = self.request()
        path = created["path"]
        source = "b" * 64
        argv = ["./gradlew", "test"]
        failure = self.evidence(source, argv, "c" * 64, 1)
        recovery = self.evidence(source, ["./gradlew", "dependencies"], "e" * 64, 0)

        with patch("work_item.validate_observed_evidence_receipt", side_effect=lambda receipt: receipt):
            self.assertEqual(
                {"status": "allowed"},
                allow_verifier_attempt(path, source_fingerprint=source, argv=argv),
            )
            self.assertEqual(
                {"status": "blocked", "reason": "verifier_failed"},
                record_verifier_failure(path, source_fingerprint=source, argv=argv,
                                        failure_receipt=failure),
            )
            self.assertEqual(
                {"status": "blocked", "reason": "identical_verifier_failure"},
                allow_verifier_attempt(path, source_fingerprint=source, argv=argv),
            )
            self.assertEqual({"status": "allowed"}, allow_verifier_attempt(
                path, source_fingerprint="d" * 64, argv=argv,
            ))
            self.assertEqual({"status": "allowed"}, allow_verifier_attempt(
                path, source_fingerprint=source, argv=["./gradlew", "check"],
            ))
            self.assertEqual({"status": "allowed"}, allow_verifier_attempt(
                path, source_fingerprint=source, argv=argv, recovery_receipt=recovery,
            ))
            self.assertEqual(
                {"status": "blocked", "reason": "verifier_failed"},
                record_verifier_failure(
                    path, source_fingerprint=source, argv=argv,
                    failure_receipt=self.evidence(source, argv, "f" * 64, 1),
                    recovery_receipt=recovery,
                ),
            )
            self.assertEqual(
                {"status": "blocked", "reason": "identical_verifier_failure"},
                allow_verifier_attempt(
                    path, source_fingerprint=source, argv=argv, recovery_receipt=recovery,
                ),
            )
            self.assertEqual({"status": "allowed"}, allow_verifier_attempt(
                path, source_fingerprint=source, argv=argv,
                recovery_receipt=self.evidence(
                    source, ["./gradlew", "properties"], "g" * 64, 0,
                ),
            ))

    def test_verifier_requires_matching_observed_failure_and_passing_recovery_evidence(self):
        created = self.request()
        path = created["path"]
        source = "b" * 64
        argv = ["./gradlew", "test"]
        wrong_failure = self.evidence(source, ["./gradlew", "check"], "c" * 64, 1)
        failed_recovery = self.evidence(source, argv, "d" * 64, 1)

        with patch("work_item.validate_observed_evidence_receipt", side_effect=lambda receipt: receipt):
            with self.assertRaisesRegex(ValueError, "failure receipt argv"):
                record_verifier_failure(path, source_fingerprint=source, argv=argv,
                                        failure_receipt=wrong_failure)
            self.assertEqual(
                {"status": "blocked", "reason": "verifier_failed"},
                record_verifier_failure(
                    path, source_fingerprint=source, argv=argv,
                    failure_receipt=self.evidence(source, argv, "e" * 64, 1),
                ),
            )
            with self.assertRaisesRegex(ValueError, "recovery receipt must pass"):
                allow_verifier_attempt(path, source_fingerprint=source, argv=argv,
                                       recovery_receipt=failed_recovery)

    def test_cli_creates_a_continuation_or_leaves_an_inline_task_stateless(self):
        receipt_path = Path(self.directory.name) / "reference-receipt.json"
        receipt_path.write_text(json.dumps(self.reference_receipt), encoding="utf-8")
        command = [
            sys.executable, str(WORK_ITEM), "resume", "--state-root", str(self.root),
            "--workspace", str(self.workspace), "--baseline", "a" * 40,
            "--target", "status-normalization", "--requirement", "normalize missing status",
            "--acceptance", "missing status normalizes to empty", "--decision", "None normalizes to empty",
            "--reference-receipt", str(receipt_path),
        ]
        created = subprocess.run(command, text=True, capture_output=True, check=False)
        inline = subprocess.run([*command, "--inline"], text=True, capture_output=True, check=False)

        self.assertEqual(0, created.returncode, created.stderr)
        self.assertEqual("created", json.loads(created.stdout)["status"])
        self.assertEqual(0, inline.returncode, inline.stderr)
        self.assertEqual({"status": "inline", "work_item": None}, json.loads(inline.stdout))

    def test_cli_verifier_gate_refuses_an_identical_recorded_failure(self):
        created = self.request()
        source = "b" * 64
        argv = ["./gradlew", "test"]
        with patch("work_item.validate_observed_evidence_receipt", side_effect=lambda receipt: receipt):
            record_verifier_failure(
                created["path"], source_fingerprint=source, argv=argv,
                failure_receipt=self.evidence(source, argv, "c" * 64, 1),
            )

        result = subprocess.run([
            sys.executable, str(WORK_ITEM), "verifier-gate", "--state", created["path"],
            "--source-fingerprint", source, "--argv-json", json.dumps(argv),
        ], text=True, capture_output=True, check=False)

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual(
            {"status": "blocked", "reason": "identical_verifier_failure"},
            json.loads(result.stdout),
        )

    def test_cli_verifier_failure_rejects_a_missing_observed_receipt(self):
        created = self.request()
        result = subprocess.run([
            sys.executable, str(WORK_ITEM), "verifier-failed", "--state", created["path"],
            "--source-fingerprint", "b" * 64, "--argv-json", json.dumps(["./gradlew", "test"]),
            "--failure-receipt", str(Path(self.directory.name) / "missing.json"),
        ], text=True, capture_output=True, check=False)

        self.assertEqual(1, result.returncode)
        self.assertEqual("error", json.loads(result.stderr)["status"])

    def test_controlled_verifier_records_a_real_failure_then_blocks_the_duplicate(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        created = resume_or_create(
            state_root=self.root, workspace=workspace, baseline=baseline,
            target="controlled-verifier", requirements=["run one verifier"],
            acceptance=["duplicate verifier execution is blocked"], decisions=[],
            reference_receipt=self.reference_receipt, continuation=True,
        )
        argv = [sys.executable, "-c", "raise SystemExit(1)"]

        failed = run_work_item_evidence(
            created["path"], workspace=workspace, baseline=baseline, argv=argv,
        )
        duplicate = run_work_item_evidence(
            created["path"], workspace=workspace, baseline=baseline, argv=argv,
        )

        self.assertEqual("blocked", failed["status"])
        self.assertEqual("verifier_failed", failed["reason"])
        self.assertEqual(1, failed["receipt"]["exit_code"])
        self.assertEqual(
            {"status": "blocked", "reason": "identical_verifier_failure"},
            duplicate,
        )

    def test_controlled_verifier_does_not_start_a_concurrent_duplicate(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        created = resume_or_create(
            state_root=self.root, workspace=workspace, baseline=baseline,
            target="concurrent-controlled-verifier", requirements=["run verifier once"],
            acceptance=["a concurrent duplicate never starts"], decisions=[],
            reference_receipt=self.reference_receipt, continuation=True,
        )
        first_started = threading.Event()
        duplicate_started = threading.Event()
        release = threading.Event()
        calls = []
        argv = [sys.executable, "-c", "raise SystemExit(1)"]

        def controlled_run(*args, **kwargs):
            calls.append(1)
            (first_started if len(calls) == 1 else duplicate_started).set()
            self.assertTrue(release.wait(timeout=5))
            return run_evidence(*args, **kwargs)

        results = []
        with patch("work_item.run_evidence", side_effect=controlled_run):
            first = threading.Thread(target=lambda: results.append(run_work_item_evidence(
                created["path"], workspace=workspace, baseline=baseline, argv=argv,
            )))
            duplicate = threading.Thread(target=lambda: results.append(run_work_item_evidence(
                created["path"], workspace=workspace, baseline=baseline, argv=argv,
            )))
            first.start()
            self.assertTrue(first_started.wait(timeout=5))
            duplicate.start()
            self.assertFalse(duplicate_started.wait(timeout=0.2))
            release.set()
            first.join(timeout=5)
            duplicate.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(duplicate.is_alive())
        self.assertEqual(1, len(calls))
        self.assertEqual(
            {"status": "blocked", "reason": "identical_verifier_failure"},
            next(result for result in results if result["reason"] == "identical_verifier_failure"),
        )

    def test_final_passing_receipt_removes_the_nonterminal_work_item(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        request = {
            "state_root": self.root, "workspace": workspace, "baseline": baseline,
            "target": "completed-controlled-verifier", "requirements": ["verify final result"],
            "acceptance": ["final verifier passes"], "decisions": [],
            "reference_receipt": self.reference_receipt, "continuation": True,
        }
        created = resume_or_create(**request)
        passed = run_work_item_evidence(
            created["path"], workspace=workspace, baseline=baseline,
            argv=[sys.executable, "-c", "pass"],
        )

        receipt_path = Path(self.directory.name) / "completion-receipt.json"
        receipt_path.write_text(json.dumps(passed["receipt"]), encoding="utf-8")
        completed = subprocess.run([
            sys.executable, str(WORK_ITEM), "complete", "--state", created["path"],
            "--workspace", str(workspace), "--baseline", baseline,
            "--receipt", str(receipt_path),
        ], text=True, capture_output=True, check=False)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual({"status": "complete"}, json.loads(completed.stdout))
        self.assertFalse(Path(created["path"]).exists())
        self.assertEqual("created", resume_or_create(**request)["status"])

    def test_completion_rejects_a_different_workspace_without_removing_the_item(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        created = resume_or_create(
            state_root=self.root, workspace=workspace, baseline=baseline,
            target="completion-workspace-boundary", requirements=["verify final result"],
            acceptance=["completion uses the frozen workspace"], decisions=[],
            reference_receipt=self.reference_receipt, continuation=True,
        )
        passed = run_work_item_evidence(
            created["path"], workspace=workspace, baseline=baseline,
            argv=[sys.executable, "-c", "pass"],
        )

        with self.assertRaisesRegex(ValueError, "completion workspace"):
            complete_work_item(
                created["path"], workspace=self.workspace, baseline=baseline,
                receipt=passed["receipt"],
            )

        self.assertTrue(Path(created["path"]).exists())

    def test_completion_rejects_a_passing_receipt_not_produced_by_the_work_item(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        created = resume_or_create(
            state_root=self.root, workspace=workspace, baseline=baseline,
            target="completion-receipt-binding", requirements=["verify final result"],
            acceptance=["only the controlled verifier can complete"], decisions=[],
            reference_receipt=self.reference_receipt, continuation=True,
        )
        unrelated_receipt = run_evidence(workspace, baseline, [sys.executable, "-c", "pass"])

        with self.assertRaisesRegex(ValueError, "not produced by the controlled verifier"):
            complete_work_item(
                created["path"], workspace=workspace, baseline=baseline,
                receipt=unrelated_receipt,
            )

        self.assertTrue(Path(created["path"]).exists())

    def test_repeated_successful_verifier_replaces_its_previous_receipt(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        created = resume_or_create(
            state_root=self.root, workspace=workspace, baseline=baseline,
            target="deduplicated-success-receipt", requirements=["run verifier"],
            acceptance=["successful verification stays bounded"], decisions=[],
            reference_receipt=self.reference_receipt, continuation=True,
        )
        argv = [sys.executable, "-c", "pass"]
        run_work_item_evidence(created["path"], workspace=workspace, baseline=baseline, argv=argv)
        latest = run_work_item_evidence(
            created["path"], workspace=workspace, baseline=baseline, argv=argv,
        )
        state = json.loads(Path(created["path"]).read_text(encoding="utf-8"))

        self.assertEqual(1, len(state["verifier_successes"]))
        self.assertEqual(latest["receipt"]["receipt_fingerprint"],
                         state["verifier_successes"][0]["receipt_fingerprint"])

    def test_controlled_verifier_rejects_a_workspace_or_baseline_outside_the_work_item(self):
        created = self.request()
        other_workspace = Path(self.directory.name) / "other-workspace"
        other_workspace.mkdir()

        with self.assertRaisesRegex(ValueError, "workspace differs"):
            run_work_item_evidence(
                created["path"], workspace=other_workspace, baseline="a" * 40,
                argv=[sys.executable, "-c", "pass"],
            )
        with self.assertRaisesRegex(ValueError, "baseline differs"):
            run_work_item_evidence(
                created["path"], workspace=self.workspace, baseline="b" * 40,
                argv=[sys.executable, "-c", "pass"],
            )

    def test_cli_controlled_verifier_runs_once_and_returns_the_failure_receipt(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        created = resume_or_create(
            state_root=self.root, workspace=workspace, baseline=baseline,
            target="controlled-verifier-cli", requirements=["run one verifier"],
            acceptance=["a failed verifier has a receipt"], decisions=[],
            reference_receipt=self.reference_receipt, continuation=True,
        )
        result = subprocess.run([
            sys.executable, str(WORK_ITEM), "verify", "--state", created["path"],
            "--workspace", str(workspace), "--baseline", baseline,
            "--argv-json", json.dumps([sys.executable, "-c", "raise SystemExit(1)"]),
        ], text=True, capture_output=True, check=False)

        self.assertEqual(2, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(("blocked", "verifier_failed"), (payload["status"], payload["reason"]))
        self.assertEqual(1, payload["receipt"]["exit_code"])

    def test_cli_controlled_verifier_accepts_an_observed_recovery_receipt(self):
        workspace = Path(__file__).resolve().parents[1]
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        created = resume_or_create(
            state_root=self.root, workspace=workspace, baseline=baseline,
            target="controlled-verifier-recovery", requirements=["run one verifier"],
            acceptance=["a valid recovery can release one retry"], decisions=[],
            reference_receipt=self.reference_receipt, continuation=True,
        )
        argv = [sys.executable, "-c", "raise SystemExit(1)"]
        first = run_work_item_evidence(
            created["path"], workspace=workspace, baseline=baseline, argv=argv,
        )
        recovery = run_evidence(
            workspace, baseline, [sys.executable, "-c", "raise SystemExit(0)"],
        )
        recovery_path = Path(self.directory.name) / "recovery.json"
        recovery_path.write_text(json.dumps(recovery), encoding="utf-8")

        result = subprocess.run([
            sys.executable, str(WORK_ITEM), "verify", "--state", created["path"],
            "--workspace", str(workspace), "--baseline", baseline,
            "--argv-json", json.dumps(argv), "--recovery-receipt", str(recovery_path),
        ], text=True, capture_output=True, check=False)

        self.assertEqual("blocked", first["status"])
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("verifier_failed", json.loads(result.stdout)["reason"])


if __name__ == "__main__":
    unittest.main()
