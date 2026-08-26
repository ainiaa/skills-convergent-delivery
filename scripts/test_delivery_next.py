import json
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from delivery_engine import controller_identity, file_fingerprint, provider_reference
from delivery_next import (
    upgrade_state, validate_execution_control, validate_provider_reference, validate_state,
)
from evidence_contract import run_evidence, workspace_source
from runner_contract import freeze_launch
from runtime_adapter import bind_observed, cleanup_receipt, negotiate
from task_profile import freeze_routing
from provider_contract import canonical_fingerprint
from worker_profile import fingerprint as worker_profile_fingerprint


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
SCRIPT = Path(__file__).with_name("delivery_next.py")
ROOT = Path(__file__).resolve().parent.parent
HEAD = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
    capture_output=True, text=True,
).stdout.strip()
SOURCE = workspace_source(ROOT, HEAD)
EVIDENCE = run_evidence(ROOT, HEAD, [sys.executable, "-c", "pass"])


def task_profile(**overrides):
    value = {
        "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
        "coupling": "single", "uncertainty": "low", "verification": "local",
        "risk_flags": [], "cross_session": False, "delegable_tasks": 0,
        "context_isolation_benefit": False,
    }
    value.update(overrides)
    return value


def routing(profile=None, allowed_paths=None):
    return freeze_routing(profile or task_profile(), allowed_paths or ["."])


def state(**overrides):
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference("native-v1", "feature"),
        "stage_providers": {},
    }
    value = {
        "schema_version": 10,
        "run_id": "run-20260818-120000",
        "workspace": str(ROOT),
        "baseline": {"commit": HEAD, "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "source_fingerprint": SOURCE["source_fingerprint"],
        "source_receipt": SOURCE,
        "execution_control": {
            "routing": routing(),
            "review": {
                "protocol_version": 3,
                "repair_budget_remaining": 1, "re_review_budget_remaining": 1,
                "integration_budget_remaining": 0,
                "rounds": [{"source_fingerprint": SOURCE["source_fingerprint"], "requests": []}],
            },
        },
        "controller": controller_identity(),
        "provider_binding": {
            "selection": "auto", "reason": "PDLC is unavailable", "task_kind": "feature",
            "binding": binding, "binding_fingerprint": canonical_fingerprint(binding),
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
                    "source_fingerprint": SOURCE["source_fingerprint"],
                    "evidence_receipts": [EVIDENCE],
                }
            ],
        },
        "handoff": {
            "goal": "Fix the requested behavior",
            "last_verification": "targeted test passed",
            "open_issues": [],
            "next_action": "Run final verification",
        },
        "workers": [],
        "worker_tree_receipt": None,
        "runtime_binding": None,
        "host_sync": {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        },
    }
    value.update(overrides)
    return value


def runtime_binding():
    return bind_observed("codex", {
        "query_id": "capabilities-codex", "observed_at": "2026-08-21T00:00:00Z",
        "profile": "codex", "capabilities": ["dispatch", "query", "wait", "interrupt", "tree_query"],
    })


def desktop_binding():
    return negotiate(
        "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                  "tree_query": True, "restrict_dispatch": False}
    )


def reviewed_complete_state(*, reviewer_registered=True, quality_mode="blind",
                            integration_budget=0, integration_status=None,
                            integration_reviewer="reviewer-a"):
    payload = upgrade_state(state(
        status="complete", current_stage="verify-final", revision=3,
        runtime_binding=runtime_binding(),
    ))
    source = payload["source_fingerprint"]
    payload["execution_control"]["routing"]["review_tier"] = "normal"
    integration_required = integration_budget == 1 or integration_status is not None
    payload["execution_control"]["routing"] = routing(task_profile(
        scope="cross-service" if integration_required else "cross-module",
        risk_flags=["cross-service"] if integration_required else [],
    ))
    review = payload["execution_control"]["review"]
    review["integration_budget_remaining"] = integration_budget
    base = {
        "phase": "initial", "source_fingerprint": source, "status": "pass",
        "reviewer_ref": "reviewer-a", "finding_fingerprints": [],
        "task_id": payload["task_key"], "request_fingerprint": "e" * 64,
    }
    requests = [
        {**base, "axis": "spec", "mode": "blind" if integration_required else "shared",
         "independent": integration_required},
        {**base, "axis": "quality", "mode": quality_mode,
         "independent": quality_mode == "blind"},
    ]
    if integration_status is not None:
        requests.append({
            **base, "axis": "integration", "status": integration_status,
            "reviewer_ref": integration_reviewer, "mode": "blind", "independent": True,
        })
    review["rounds"] = [{"source_fingerprint": source, "requests": requests}]
    if reviewer_registered:
        payload["workers"] = [{
            "ref": "reviewer-a", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "completed", "progress": None,
        }]
        if integration_reviewer != "reviewer-a":
            payload["workers"].append({
                "ref": integration_reviewer, "parent_ref": None,
                "task_id": payload["task_key"], "depth": 1, "may_dispatch": False,
                "role": "reviewer", "owner_run_id": payload["run_id"],
                "status": "completed", "progress": None,
            })
        reviewer_refs = [worker["ref"] for worker in payload["workers"]]
        observation = {
            "query_id": "query-reviewers", "observed_at": "2026-08-21T00:00:00Z",
            "registered_refs": reviewer_refs, "active_refs": [], "unexpected_refs": [],
        }
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, reviewer_refs, [], [],
            "2026-08-21T00:00:00Z", host_observation=observation,
        )
    return payload


class DeliveryNextTest(unittest.TestCase):
    def test_caller_cannot_override_the_canonical_profile_route(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"]["route"] = "batch"

        with self.assertRaisesRegex(ValueError, "canonical task profile"):
            validate_state(payload, SimpleNamespace())

    def test_completion_rejects_scope_and_risk_drift_from_the_frozen_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.email", "test@example.com"], check=True)
            (workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "seed.txt"], check=True)
            subprocess.run(["git", "-C", str(workspace), "commit", "-q", "-m", "seed"], check=True)
            baseline = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            (workspace / "db").mkdir()
            (workspace / "db" / "permission.sql").write_text("select 1;\n", encoding="utf-8")
            source = workspace_source(workspace, baseline)
            payload = upgrade_state(state())
            payload.update(
                status="complete", current_stage="verify-final", workspace=str(workspace),
                repo_id=str(workspace / ".git"),
                baseline={"commit": baseline, "diff_fingerprint": "clean"},
                source_fingerprint=source["source_fingerprint"], source_receipt=source,
            )
            payload["ledger"]["acceptance"][0]["source_fingerprint"] = source["source_fingerprint"]
            payload["ledger"]["acceptance"][0]["evidence_receipts"] = [
                run_evidence(workspace, baseline, [sys.executable, "-c", "pass"])
            ]
            payload["execution_control"]["review"]["rounds"] = []
            payload["execution_control"]["routing"] = routing(
                task_profile(), ["docs"]
            )

            with self.assertRaisesRegex(ValueError, "scope drift"):
                validate_state(payload, SimpleNamespace())

            payload["execution_control"]["routing"] = routing(task_profile(), ["db"])
            with self.assertRaisesRegex(ValueError, "risk exceeds"):
                validate_state(payload, SimpleNamespace())

    def test_current_complete_state_requires_real_source_and_command_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.email", "test@example.com"], check=True)
            (workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "seed.txt"], check=True)
            subprocess.run(["git", "-C", str(workspace), "commit", "-q", "-m", "seed"], check=True)
            baseline = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            payload = upgrade_state(state())
            payload.update(
                schema_version=10, status="complete", current_stage="verify-final",
                workspace=str(workspace), repo_id=str(workspace / ".git"),
                baseline={"commit": baseline, "diff_fingerprint": "clean"},
            )
            receipt = workspace_source(workspace, baseline)
            payload["source_fingerprint"] = receipt["source_fingerprint"]
            payload["execution_control"]["review"]["rounds"] = []
            payload["ledger"]["acceptance"][0]["source_fingerprint"] = receipt["source_fingerprint"]
            payload.pop("source_receipt")
            payload["ledger"]["acceptance"][0].pop("evidence_receipts")

            with self.assertRaisesRegex(ValueError, "source_receipt"):
                validate_state(payload, SimpleNamespace())

            payload["source_receipt"] = receipt
            with self.assertRaisesRegex(ValueError, "Evidence Receipt"):
                validate_state(payload, SimpleNamespace())

            payload["ledger"]["acceptance"][0]["evidence_receipts"] = [
                run_evidence(workspace, baseline, [sys.executable, "-c", "pass"])
            ]
            self.assertEqual("complete", validate_state(payload, SimpleNamespace()))

            profile = {
                "schema_version": 1, "worker_id": "research-1", "role": "research",
                "runner_id": "openai-compatible-v1",
                "requested": {"model": "glm-5.2", "reasoning_effort": "high"},
                "effective": {"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
                "permissions": {"workspace": "read", "shell": False, "network": "egress"},
                "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 12000},
            }
            profile["profile_fingerprint"] = worker_profile_fingerprint(profile)
            payload["ledger"]["runner_launches"] = [
                freeze_launch(profile, "Review", {"api_key_env": "GLM_API_KEY"})
            ]
            with self.assertRaisesRegex(ValueError, "runner launch"):
                validate_state(payload, SimpleNamespace())

    def test_legacy_single_state_schemas_are_rejected(self):
        for schema_version in range(5, 10):
            with self.subTest(schema_version=schema_version):
                payload = state(schema_version=schema_version)
                with self.assertRaisesRegex(ValueError, "schema_version must be 10"):
                    upgrade_state(payload)

    def test_unknown_single_state_fields_are_rejected(self):
        for field in ("legacy_marker", "misspelled_state_field"):
            with self.subTest(field=field):
                payload = state(**{field: True})
                with self.assertRaisesRegex(ValueError, "state fields are invalid"):
                    validate_state(payload, SimpleNamespace())

    def test_unknown_persisted_single_state_fields_are_rejected(self):
        def history_entry(payload, field):
            payload["ledger"]["acceptance_history"] = [{
                "revision": 0,
                "acceptance": dict(payload["ledger"]["acceptance"][0]),
            }]
            payload["ledger"]["acceptance_history"][0][field] = True

        def acceptance_snapshot(payload, field):
            payload["ledger"]["acceptance_history"] = [{
                "revision": 0,
                "acceptance": dict(payload["ledger"]["acceptance"][0]),
            }]
            payload["ledger"]["acceptance_history"][0]["acceptance"][field] = True

        cases = (
            ("baseline", lambda value: value["baseline"].__setitem__("legacy_marker", True)),
            ("handoff", lambda value: value["handoff"].__setitem__("legacy_marker", True)),
            ("check", lambda value: value["ledger"]["checks"].append({
                "stage": "test", "command": "true", "result": "pass", "legacy_marker": True,
            })),
            ("acceptance", lambda value: value["ledger"]["acceptance"][0].__setitem__("legacy_marker", True)),
            ("acceptance history", lambda value: history_entry(value, "legacy_marker")),
            ("acceptance snapshot", lambda value: acceptance_snapshot(value, "legacy_marker")),
        )
        for location, mutate in cases:
            with self.subTest(location=location):
                payload = state()
                mutate(payload)
                with self.assertRaisesRegex(ValueError, "fields are invalid"):
                    validate_state(payload, SimpleNamespace())

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

    def test_rejects_undocumented_ledger_data(self):
        payload = upgrade_state(state())
        payload["ledger"]["prompt"] = "confidential worker prompt"

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("ledger fields", result.stderr)

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
        payload["host_sync"] = {
            "mode": "native", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        }

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

    def test_active_worker_allows_a_trusted_codex_desktop_binding(self):
        payload = upgrade_state(state())
        payload["runtime_binding"] = desktop_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        self.assertEqual("verify-final", validate_state(payload, SimpleNamespace()))

    def test_active_worker_allows_a_trusted_claude_code_binding(self):
        payload = upgrade_state(state())
        payload["runtime_binding"] = negotiate(
            "claude-code", {"dispatch": True, "query": True, "tree_query": True}
        )
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        self.assertEqual("verify-final", validate_state(payload, SimpleNamespace()))

    def test_cross_session_worker_requires_a_host_observed_binding(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = routing(task_profile(cross_session=True))
        payload["runtime_binding"] = desktop_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "cross-session worker"):
            validate_state(payload, SimpleNamespace())

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

        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, ["worker-1"], [], [],
            "2026-08-21T00:00:00Z",
            host_observation={
                "query_id": "query-clean", "observed_at": "2026-08-21T00:00:00Z",
                "registered_refs": ["worker-1"], "active_refs": [],
                "unexpected_refs": [],
            },
        )
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

    def test_complete_with_workers_allows_trusted_codex_desktop_cleanup(self):
        payload = reviewed_complete_state()
        payload["runtime_binding"] = desktop_binding()
        refs = [worker["ref"] for worker in payload["workers"]]
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, refs, [], [], "2026-08-21T00:00:00Z"
        )

        self.assertEqual("complete", validate_state(payload, SimpleNamespace()))

    def test_high_risk_complete_requires_current_spec_and_quality_reviews(self):
        payload = state(status="complete", current_stage="verify-final")
        payload["execution_control"]["routing"] = routing(
            task_profile(risk_flags=["money"])
        )

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("review", result.stderr)

    def test_normal_review_requires_a_registered_completed_reviewer(self):
        payload = reviewed_complete_state(reviewer_registered=False)

        with self.assertRaisesRegex(ValueError, "registered completed reviewer"):
            validate_state(payload, SimpleNamespace())

    def test_normal_review_requires_initial_quality_to_be_independent_and_blind(self):
        payload = reviewed_complete_state(quality_mode="shared")

        with self.assertRaisesRegex(ValueError, "quality.*independent blind"):
            validate_state(payload, SimpleNamespace())

    def test_normal_review_accepts_shared_spec_and_blind_quality_from_one_reviewer(self):
        payload = reviewed_complete_state()

        self.assertEqual("complete", validate_state(payload, SimpleNamespace()))

    def test_required_integration_review_cannot_remain_unspent_at_completion(self):
        payload = reviewed_complete_state(integration_budget=1)

        with self.assertRaisesRegex(ValueError, "integration review is still required"):
            validate_state(payload, SimpleNamespace())

    def test_consumed_integration_review_requires_a_current_pass(self):
        payload = reviewed_complete_state(integration_status="findings")
        payload["execution_control"]["review"]["rounds"][0]["requests"][-1][
            "finding_fingerprints"
        ] = ["d" * 64]

        with self.assertRaisesRegex(ValueError, "integration review requires a current pass"):
            validate_state(payload, SimpleNamespace())

    def test_integration_may_use_a_different_registered_reviewer(self):
        payload = reviewed_complete_state(
            integration_status="pass", integration_reviewer="reviewer-b"
        )

        self.assertEqual("complete", validate_state(payload, SimpleNamespace()))

    def test_later_review_finding_invalidates_an_earlier_pass(self):
        payload = upgrade_state(state(status="complete", current_stage="verify-final"))
        payload["execution_control"]["routing"] = routing(
            task_profile(risk_flags=["money"])
        )
        source = payload["source_fingerprint"]
        base = {
            "phase": "initial", "source_fingerprint": source,
            "reviewer_ref": "reviewer-a", "mode": "blind", "independent": True,
            "finding_fingerprints": [], "task_id": payload["task_key"],
            "request_fingerprint": "e" * 64,
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
                        "task_id": "task-123", "request_fingerprint": "4" * 64,
                    }],
                },
                {
                    "source_fingerprint": current_source,
                    "requests": [{
                        "axis": "spec", "phase": "re_review",
                        "source_fingerprint": current_source, "status": "pass",
                        "reviewer_ref": "reviewer-a", "mode": "shared",
                        "independent": False, "finding_fingerprints": [],
                        "task_id": "task-123", "request_fingerprint": "5" * 64,
                    }],
                },
            ],
        }

        routing, review = validate_execution_control(control, current_source)

        self.assertEqual("high" if routing["review_tier"] == "high" else "low", routing["review_tier"])
        self.assertEqual(2, len(review["rounds"]))

    def test_review_round_accepts_matching_structured_finding_records(self):
        control = state()["execution_control"]
        source = control["review"]["rounds"][0]["source_fingerprint"]
        control["review"]["rounds"][0]["requests"] = [{
            "axis": "spec", "phase": "initial", "source_fingerprint": source,
            "status": "findings", "reviewer_ref": "reviewer-a", "mode": "shared",
            "independent": False, "finding_fingerprints": ["b" * 64],
            "finding_records": [{
                "fingerprint": "b" * 64, "evidence": "test.py:10 fails",
                "impact": "the acceptance can falsely pass",
                "root_cause": "the source receipt is missing", "scope": "current",
                "classification": "defect",
            }],
            "task_id": "task-123", "request_fingerprint": "c" * 64,
        }]

        _, review = validate_execution_control(control, source, "task-123")

        self.assertEqual("the acceptance can falsely pass", review["rounds"][0]["requests"][0]["finding_records"][0]["impact"])

    def test_review_round_rejects_mismatched_structured_finding_records(self):
        control = state()["execution_control"]
        source = control["review"]["rounds"][0]["source_fingerprint"]
        control["review"]["rounds"][0]["requests"] = [{
            "axis": "spec", "phase": "initial", "source_fingerprint": source,
            "status": "findings", "reviewer_ref": "reviewer-a", "mode": "shared",
            "independent": False, "finding_fingerprints": ["b" * 64],
            "finding_records": [{
                "fingerprint": "d" * 64, "evidence": "test.py:10 fails",
                "impact": "the acceptance can falsely pass",
                "root_cause": "the source receipt is missing", "scope": "current",
                "classification": "defect",
            }],
            "task_id": "task-123", "request_fingerprint": "c" * 64,
        }]

        with self.assertRaisesRegex(ValueError, "finding_records do not match"):
            validate_execution_control(control, source, "task-123")

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

    def test_legacy_engine_state_is_rejected(self):
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


if __name__ == "__main__":
    unittest.main()
