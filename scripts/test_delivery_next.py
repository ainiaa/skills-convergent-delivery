import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from delivery_engine import file_fingerprint, legacy_pdlc_fingerprint, provider_reference
from delivery_next import upgrade_state, validate_execution_control, validate_provider_reference
from runtime_adapter import cleanup_receipt, negotiate


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
SCRIPT = Path(__file__).with_name("delivery_next.py")


def state(**overrides):
    value = {
        "schema_version": 5,
        "run_id": "run-20260818-120000",
        "workspace": "/workspace/service",
        "baseline": {"commit": "abc123", "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "source_fingerprint": "a" * 64,
        "execution_control": {
            "routing": {
                "schema_version": 1, "status": "frozen", "assessment_count": 1,
                "route": "inline", "review_tier": "low", "profile_fingerprint": "b" * 64,
            },
            "review": {
                "protocol_version": 2, "source_fingerprint": "a" * 64,
                "repair_budget_remaining": 1, "re_review_budget_remaining": 1,
                "integration_budget_remaining": 0, "requests": [],
            },
        },
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
                    "source_fingerprint": "a" * 64,
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


def runtime_binding():
    return negotiate(
        "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                  "tree_query": True, "restrict_dispatch": False}
    )


class DeliveryNextTest(unittest.TestCase):
    def test_v6_migration_rejects_an_unknown_frozen_controller(self):
        payload = state(
            schema_version=6,
            controller={"version": "forged", "fingerprint": "0" * 64},
        )

        with self.assertRaisesRegex(ValueError, "legacy controller"):
            upgrade_state(payload)

    def test_v6_migration_accepts_the_published_0_10_controller(self):
        payload = state(
            schema_version=6,
            controller={
                "version": "0.10.0",
                "fingerprint": "843047313fb0c0c7b068e4a7033fe51a7ffec62aaf4234aaf86893c48144a485",
            },
        )

        self.assertEqual(10, upgrade_state(payload)["schema_version"])

    def test_v8_state_with_workers_requires_manual_recovery(self):
        payload = upgrade_state(state())
        payload["schema_version"] = 8
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "manual recovery"):
            upgrade_state(payload)

    def test_v9_state_with_workers_requires_manual_recovery(self):
        payload = upgrade_state(state())
        payload["schema_version"] = 9
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "manual recovery"):
            upgrade_state(payload)

    def test_v8_state_without_workers_migrates_without_inventing_host_facts(self):
        payload = upgrade_state(state())
        payload["schema_version"] = 8

        migrated = upgrade_state(payload)

        self.assertEqual(10, migrated["schema_version"])
        self.assertEqual([], migrated["workers"])

    def test_frozen_provider_reference_rejects_manifest_identity_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).resolve().parent.parent / "providers" / "native-v1.json"
            for field, value in (("version", "2"), ("role", "stage")):
                with self.subTest(field=field):
                    manifest = json.loads(source.read_text(encoding="utf-8"))
                    manifest["provider"][field] = value
                    path = Path(directory) / f"native-{field}.json"
                    path.write_text(json.dumps(manifest), encoding="utf-8")
                    reference = provider_reference("native-v1")
                    reference.update(
                        manifest=str(path.resolve()),
                        manifest_fingerprint=file_fingerprint(path),
                    )

                    with self.assertRaisesRegex(ValueError, "identity changed"):
                        validate_provider_reference(reference, "workflow", "feature")

    def pdlc_engine(self, directory):
        root = Path(directory) / "pdlc"
        for name in ("pdlc-tdd", "pdlc-implement", "pdlc-review", "pdlc-feature"):
            path = root / "skills" / name / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name}\n", encoding="utf-8")
        files = [
            "pdlc-feature/SKILL.md",
            "pdlc-tdd/SKILL.md",
            "pdlc-implement/SKILL.md",
            "pdlc-review/SKILL.md",
        ]
        digest = hashlib.sha256()
        for relative in files:
            digest.update(relative.encode() + b"\0" + (root / "skills" / relative).read_bytes())
        (root / "converge-provider.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "provider": {
                        "id": "pdlc-v1",
                        "source_id": "pdlc-skills",
                        "version": "test-v1",
                        "role": "workflow",
                    },
                    "capabilities": {
                        "task_kinds": ["feature"],
                        "stages": ["plan", "tdd", "implement", "review"],
                    },
                    "task_contracts": {
                        "feature": {
                            "entrypoint": files[0],
                            "closure": files[1:],
                            "source_fingerprint": digest.hexdigest(),
                            "preserve_external_behavior": False,
                        }
                    },
                    "authorization": {
                        "stop_for": [
                            "business_rules", "public_contracts", "permissions",
                            "release", "irreversible_actions",
                        ],
                        "forbidden_actions": [
                            "pdlc-ship", "commit", "tag", "push", "publish", "install",
                        ],
                    },
                    "outputs": {
                        "progress_protocol": 1,
                        "required_evidence": ["tests", "validation", "findings"],
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "name": "pdlc-v1",
            "selection": "explicit",
            "reason": "PDLC v1 is available",
            "pdlc_root": str(root.resolve()),
            "feature_id": "F-123",
            "task_kind": "feature",
            "pdlc_fingerprint": legacy_pdlc_fingerprint(root, "feature"),
            "provider_manifest": str(root / "converge-provider.json"),
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

    def run_helper(self, payload, *, run_id=None, writer_id=None, revision=None, acquire=True, output_format="legacy"):
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
                "--format",
                output_format,
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

    def test_json_output_uses_shared_action_contract(self):
        payload = state()
        result = self.run_helper(
            payload, run_id=payload["run_id"], writer_id=payload["writer_id"], revision=0,
            output_format="json",
        )

        self.assertEqual(
            {"action": "verify", "task_id": "task-123", "phase": "verify-final"},
            json.loads(result.stdout),
        )
        self.assertEqual(0, result.returncode)

    def test_native_host_plan_must_be_acknowledged_before_business_action(self):
        payload = upgrade_state(state())
        payload["host_sync"] = {"mode": "native", "acknowledged_fingerprint": None}

        result = self.run_helper(
            payload, run_id=payload["run_id"], writer_id=payload["writer_id"],
            revision=payload["revision"], output_format="json",
        )

        output = json.loads(result.stdout)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("sync-plan", output["action"])
        self.assertEqual(64, len(output["projection_fingerprint"]))

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

    def test_active_and_complete_states_reject_blocked_metadata(self):
        for status, stage in (("active", "round-1-semantic-review"), ("complete", "verify-final")):
            with self.subTest(status=status):
                result = self.current(state(
                    status=status,
                    current_stage=stage,
                    blocked_code="environment",
                    blocked_reason="stale reason",
                ))

                self.assertNotEqual(0, result.returncode)
                self.assertIn("blocked", result.stderr)

    def test_worker_task_id_must_match_the_state_task_key(self):
        payload = upgrade_state(state())
        payload["runtime_binding"] = runtime_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": "another-task",
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("task", result.stderr)

    def test_state_requires_a_frozen_route_and_persisted_assessment_count(self):
        payload = upgrade_state(state())
        payload.pop("execution_control")

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("execution_control", result.stderr)

    def test_complete_acceptance_must_match_the_current_source_fingerprint(self):
        payload = state(status="complete", current_stage="verify-final")
        payload["ledger"]["acceptance"][0]["source_fingerprint"] = "c" * 64

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("source", result.stderr)

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

    def test_complete_with_workers_requires_fresh_clean_tree_receipt(self):
        worker = {
            "ref": "worker-1", "parent_ref": None, "task_id": "task-123",
            "depth": 1, "may_dispatch": False,
            "role": "reviewer",
            "owner_run_id": "run-20260818-120000",
            "status": "completed",
            "progress": None,
        }
        payload = upgrade_state(state(
            status="complete", current_stage="verify-final", revision=3,
            runtime_binding=runtime_binding(),
        ))
        payload["workers"] = [worker]
        payload = upgrade_state(payload)

        missing = self.current(payload, revision=3)
        self.assertNotEqual(0, missing.returncode)
        self.assertIn("tree receipt", missing.stderr)

        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, ["worker-1"], [], ["nested-worker"],
            "2026-08-21T00:00:00Z",
        )
        unexpected = self.current(payload, revision=3)
        self.assertNotEqual(0, unexpected.returncode)
        self.assertIn("unexpected", unexpected.stderr)

        payload["worker_tree_receipt"]["unexpected_refs"] = []
        clean = self.current(payload, revision=3)
        self.assertEqual(0, clean.returncode, clean.stderr)
        self.assertEqual("complete\n", clean.stdout)

    def test_complete_rejects_unexpected_descendants_even_with_empty_registry(self):
        payload = upgrade_state(state(
            status="complete", current_stage="verify-final", revision=3,
            runtime_binding=runtime_binding(),
        ))
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, [], [], ["unregistered-worker"],
            "2026-08-21T00:00:00Z",
        )

        result = self.current(payload, revision=3)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unexpected", result.stderr)

    def test_high_risk_complete_requires_current_spec_and_quality_reviews(self):
        payload = state(status="complete", current_stage="verify-final")
        payload["execution_control"]["routing"]["review_tier"] = "high"

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("review", result.stderr)

    def test_later_review_finding_invalidates_an_earlier_pass(self):
        payload = upgrade_state(state(status="complete", current_stage="verify-final"))
        payload["execution_control"]["routing"]["review_tier"] = "high"
        source = payload["source_fingerprint"]
        base = {
            "phase": "initial", "source_fingerprint": source,
            "reviewer_ref": "reviewer-a", "mode": "blind", "independent": True,
            "finding_fingerprints": [],
        }
        payload["execution_control"]["review"]["rounds"] = [{
            "source_fingerprint": source,
            "requests": [
                {**base, "axis": "spec", "status": "pass"},
                {**base, "axis": "quality", "status": "pass"},
                {**base, "axis": "quality", "status": "findings",
                 "finding_fingerprints": ["d" * 64]},
            ],
        }]

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("review", result.stderr)

    def test_review_history_keeps_old_rounds_after_source_changes(self):
        old_source = "1" * 64
        current_source = "2" * 64
        control = state()["execution_control"]
        control["review"] = {
            "protocol_version": 3,
            "repair_budget_remaining": 0,
            "re_review_budget_remaining": 0,
            "integration_budget_remaining": 0,
            "rounds": [
                {
                    "source_fingerprint": old_source,
                    "requests": [{
                        "axis": "quality", "phase": "initial",
                        "source_fingerprint": old_source, "status": "findings",
                        "reviewer_ref": "reviewer-a", "mode": "shared",
                        "independent": False, "finding_fingerprints": ["3" * 64],
                    }],
                },
                {
                    "source_fingerprint": current_source,
                    "requests": [{
                        "axis": "spec", "phase": "re_review",
                        "source_fingerprint": current_source, "status": "pass",
                        "reviewer_ref": "reviewer-a", "mode": "shared",
                        "independent": False, "finding_fingerprints": [],
                    }],
                },
            ],
        }

        routing, review = validate_execution_control(control, current_source)

        self.assertEqual("high" if routing["review_tier"] == "high" else "low", routing["review_tier"])
        self.assertEqual(2, len(review["rounds"]))

    def test_blocked_with_active_worker_requires_fresh_cleanup_receipt(self):
        worker = {
            "ref": "worker-1", "parent_ref": None, "task_id": "task-123",
            "depth": 1, "may_dispatch": False,
            "role": "reviewer",
            "owner_run_id": "run-20260818-120000",
            "status": "working",
            "progress": None,
        }
        payload = upgrade_state(state(
            status="blocked",
            blocked_code="environment",
            blocked_reason="manual cleanup required",
            revision=4,
            runtime_binding=runtime_binding(),
        ))
        payload["workers"] = [worker]
        payload = upgrade_state(payload)

        missing = self.current(payload, revision=4)
        self.assertNotEqual(0, missing.returncode)
        self.assertIn("cleanup receipt", missing.stderr)

        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 4, ["worker-1"], ["worker-1"], [],
            "2026-08-21T00:00:00Z",
        )
        recorded = self.current(payload, revision=4)
        self.assertEqual(0, recorded.returncode, recorded.stderr)
        self.assertEqual("blocked\n", recorded.stdout)

    def test_invalid_state_emits_blocked(self):
        result = self.current(state(schema_version=4))

        self.assertEqual("blocked\n", result.stdout)
        self.assertNotEqual(0, result.returncode)

    def test_invalid_state_json_block_action_keeps_task_identity(self):
        payload = state(schema_version=4)
        result = self.run_helper(
            payload, run_id=payload["run_id"], writer_id=payload["writer_id"],
            revision=payload["revision"], output_format="json",
        )

        self.assertEqual("task-123", json.loads(result.stdout)["task_id"])

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
