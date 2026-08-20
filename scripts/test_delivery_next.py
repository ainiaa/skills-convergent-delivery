import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from delivery_engine import file_fingerprint, pdlc_fingerprint


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
SCRIPT = Path(__file__).with_name("delivery_next.py")


def state(**overrides):
    value = {
        "schema_version": 5,
        "run_id": "run-20260818-120000",
        "workspace": "/workspace/service",
        "baseline": {"commit": "abc123", "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "engine": {
            "name": "native-v1",
            "selection": "auto",
            "reason": "PDLC is unavailable",
        },
        "repo_id": "/repo/common.git",
        "task_key": "task-123",
        "writer_id": "writer-123",
        "revision": 0,
        "current_stage": "round-1-semantic-review",
        "requires_stability_round": False,
        "status": "active",
        "ledger": {
            "completed_rounds": 0,
            "repair_fingerprints": [],
            "checks": [],
            "acceptance": [
                {
                    "criterion": "Requested behavior",
                    "evidence": "targeted test",
                    "result": "pass",
                    "freshness": "fresh",
                }
            ],
        },
        "handoff": {
            "goal": "Fix the requested behavior",
            "last_verification": "targeted test passed",
            "open_issues": "none",
            "next_action": "Run final verification",
        },
    }
    value.update(overrides)
    return value


class DeliveryNextTest(unittest.TestCase):
    def pdlc_engine(self, directory):
        root = Path(directory) / "pdlc"
        for name in ("pdlc-tdd", "pdlc-implement", "pdlc-review", "pdlc-feature"):
            path = root / "skills" / name / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name}\n", encoding="utf-8")
        return {
            "name": "pdlc-v1",
            "selection": "explicit",
            "reason": "PDLC v1 is available",
            "pdlc_root": str(root.resolve()),
            "feature_id": "F-123",
            "task_kind": "feature",
            "pdlc_fingerprint": pdlc_fingerprint(root, "feature"),
        }

    def generic_tdd_engine(self, directory):
        path = Path(directory) / "project-tdd" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Run a test first, then use the red and green cycle.\n", encoding="utf-8")
        return {
            "name": "generic-tdd-v1",
            "selection": "auto",
            "reason": "generic TDD provider is available",
            "tdd_skill_path": str(path.resolve()),
            "tdd_skill_fingerprint": file_fingerprint(path),
        }, path

    def run_helper(self, payload, *, run_id=None, writer_id=None, revision=None, acquire=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            if acquire:
                lease = subprocess.run(
                    [
                        sys.executable,
                        str(LEASE_SCRIPT),
                        "acquire",
                        "--root",
                        str(root),
                        "--repo",
                        payload["repo_id"],
                        "--workspace",
                        payload["workspace"],
                        "--task-key",
                        payload["task_key"],
                        "--run-id",
                        payload["run_id"],
                        "--writer-id",
                        payload["writer_id"],
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, lease.returncode, lease.stderr)
            arguments = [
                sys.executable,
                str(SCRIPT),
                "--state",
                str(path),
                "--lease-root",
                str(root),
            ]
            if run_id is not None:
                arguments.extend(["--run-id", run_id])
            if writer_id is not None:
                arguments.extend(["--writer-id", writer_id])
            if revision is not None:
                arguments.extend(["--revision", str(revision)])
            return subprocess.run(arguments, text=True, capture_output=True, check=False)

    def current(self, payload=None, **overrides):
        payload = payload or state()
        return self.run_helper(
            payload,
            run_id=overrides.get("run_id", payload["run_id"]),
            writer_id=overrides.get("writer_id", payload["writer_id"]),
            revision=overrides.get("revision", payload["revision"]),
            acquire=overrides.get("acquire", True),
        )

    def test_low_risk_semantic_review_moves_to_final_verification(self):
        result = self.current()

        self.assertEqual("verify-final\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_high_risk_semantic_review_moves_to_round_one_verification(self):
        result = self.current(state(requires_stability_round=True))

        self.assertEqual("verify-round-1\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_complete_state_emits_complete(self):
        result = self.current(state(status="complete", current_stage="verify-final"))

        self.assertEqual("complete\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_应该_当终态缺少阶段必需字段时_拒绝恢复(self):
        for status in ("complete", "blocked"):
            for missing in ("requires_stability_round", "current_stage"):
                with self.subTest(status=status, missing=missing):
                    payload = state(
                        status=status,
                        current_stage="verify-final",
                        blocked_code="decision" if status == "blocked" else None,
                        blocked_reason="decision required" if status == "blocked" else None,
                    )
                    payload.pop(missing)

                    result = self.current(payload)

                    self.assertEqual("blocked\n", result.stdout)
                    self.assertNotEqual(0, result.returncode)

    def test_blocked_state_emits_blocked(self):
        result = self.current(
            state(
                status="blocked",
                blocked_code="decision",
                blocked_reason="A business decision is required",
            )
        )

        self.assertEqual("blocked\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_complete_state_requires_fresh_passing_acceptance_evidence(self):
        result = self.current(
            state(
                status="complete",
                current_stage="verify-final",
                ledger={
                    "completed_rounds": 1,
                    "repair_fingerprints": [],
                    "checks": [],
                    "acceptance": [
                        {
                            "criterion": "Requested behavior",
                            "evidence": "old targeted test",
                            "result": "pass",
                            "freshness": "stale",
                        }
                    ],
                },
            )
        )

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_invalid_state_emits_blocked(self):
        result = self.current(state(schema_version=4))

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_relative_repo_id_emits_blocked(self):
        result = self.current(state(repo_id="relative/repo"), acquire=False)

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_mismatched_run_id_emits_blocked(self):
        result = self.current(run_id="other-run")

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_mismatched_writer_id_emits_blocked(self):
        result = self.current(writer_id="other-writer")

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_invalid_revision_emits_blocked(self):
        result = self.current(revision=-1)

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_missing_identity_or_active_lease_emits_blocked(self):
        missing = self.run_helper(state(), acquire=False)
        inactive = self.current(acquire=False)

        self.assertEqual("blocked\n", missing.stdout)
        self.assertNotEqual(0, missing.returncode)
        self.assertEqual("blocked\n", inactive.stdout)
        self.assertNotEqual(0, inactive.returncode)

    def test_active_final_verification_state_must_not_restart(self):
        result = self.current(state(current_stage="verify-final"))

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_active_pdlc_task_only_delegates_to_the_pdlc_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.current(
                state(current_stage="pdlc-run", engine=self.pdlc_engine(directory))
            )

        self.assertEqual("pdlc-run\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_pdlc_task_rejects_a_native_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.current(
                state(engine=self.pdlc_engine(directory))
            )

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_pdlc_task_rejects_a_changed_frozen_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = self.pdlc_engine(directory)
            Path(engine["pdlc_root"], "skills", "pdlc-review", "SKILL.md").write_text(
                "changed\n", encoding="utf-8"
            )
            result = self.current(state(current_stage="pdlc-run", engine=engine))

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_adapted_tdd_task_uses_native_stages_with_a_frozen_skill_path(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, _ = self.generic_tdd_engine(directory)
            result = self.current(
                state(engine=engine)
            )

        self.assertEqual("verify-final\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_third_party_tdd_task_rejects_missing_or_changed_frozen_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, path = self.generic_tdd_engine(directory)
            path.write_text("Run a test first, then use the red and green cycle. Changed.\n", encoding="utf-8")
            result = self.current(
                state(engine=engine)
            )

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_native_task_rejects_embedded_pdlc_state(self):
        result = self.current(
            state(
                engine={
                    "name": "native-v1",
                    "selection": "auto",
                    "reason": "PDLC is unavailable",
                    "pdlc_root": "/tools/pdlc-skills",
                }
            )
        )

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_native_task_rejects_a_third_party_tdd_fingerprint(self):
        result = self.current(
            state(
                engine={
                    "name": "native-v1",
                    "selection": "auto",
                    "reason": "PDLC is unavailable",
                    "tdd_skill_fingerprint": "should-not-be-here",
                }
            )
        )

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
