import copy
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from delivery_engine import controller_identity, file_fingerprint, provider_reference
from autonomy_contract import validate_autonomy_completion
from delivery_next import (
    upgrade_state, validate_execution_control, validate_provider_reference, closure_graph_query,
    validate_closure_gate, validate_closure_plan, validate_state,
)
from delivery_state import validate_transition
from evidence_contract import run_evidence, workspace_source
from role_result import review_result, result_from_output
from runner_contract import bind_role_result, fingerprint as runner_fingerprint, freeze_launch
from run_contract import action
from runtime_adapter import _bind, cleanup_receipt as runtime_cleanup_receipt, negotiate
from task_profile import freeze_routing
from provider_contract import canonical_fingerprint
from worker_profile import fingerprint as worker_profile_fingerprint


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
SCRIPT = Path(__file__).with_name("delivery_next.py")
ROOT = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", Path(__file__).resolve().parent.parent)).resolve()
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


def graph_receipt(source_fingerprint, routing_value, plan, tool="codegraph", query=None):
    # Test receipt binding independently of a locally installed graph service.
    with tempfile.TemporaryDirectory() as directory:
        executable = Path(directory) / tool
        executable.write_text(f"#!{sys.executable}\nprint('fixture graph output')\n", encoding="utf-8")
        executable.chmod(0o700)
        with patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ.get("PATH", "")}):
            evidence = run_evidence(ROOT, HEAD, [
                tool, "explore", query or closure_graph_query(routing_value, plan),
            ])
    evidence["receipt_fingerprint"] = runner_fingerprint({
        key: item for key, item in evidence.items() if key != "receipt_fingerprint"
    })
    value = {
        "schema_version": 1, "tool": tool,
        "source_fingerprint": source_fingerprint,
        "scope_fingerprint": routing_value["profile_fingerprint"],
        "output_fingerprint": evidence["stdout_fingerprint"], "evidence": evidence,
    }
    return {**value, "receipt_fingerprint": runner_fingerprint(value)}


def closure_plan(requirement_fingerprint=None):
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference("native-v1", "feature"),
        "stage_providers": {},
    }
    provider_binding = {
        "selection": "auto", "reason": "PDLC is unavailable", "task_kind": "feature",
        "binding": binding, "binding_fingerprint": canonical_fingerprint(binding),
    }
    chain = {
        "id": "main", "description": "the frozen closure chain", "entrypoints": ["."],
        "callers": ["external"],
        "coverage": {
            item: {"status": "covered", "acceptance": ["Requested behavior"]}
            for item in ("input", "freeze", "effect", "receipt", "recovery")
        },
    }
    projection = [{key: chain[key] for key in ("id", "entrypoints", "callers")}]
    receipt = {
        "schema_version": 1, "tool": "codegraph", "source_fingerprint": SOURCE["source_fingerprint"],
        "chains_fingerprint": hashlib.sha256(json.dumps(
            projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
    }
    return {
        "schema_version": 6, "plan_id": "plan-closure",
        "requirement_fingerprint": requirement_fingerprint or routing()["request_fingerprint"],
        "planner": {"name": "native-plan-v1", "source_path": None, "source_fingerprint": None},
        "context": "short", "baseline": {"commit": HEAD, "source": copy.deepcopy(SOURCE)},
        "tasks": [{
            "task_id": "closure", "task_kind": "vertical_slice", "outcomes": ["close scope"],
            "goal": "close scope", "owned_paths": ["."], "depends_on": [],
            "steps": ["verify closure"], "acceptance": ["Requested behavior"],
            "verification": ["python3 scripts/test_delivery_next.py"], "execution": "current",
            "status": "pending", "provider_binding": provider_binding,
            "provider_run": {"scope": "task", "recursive_planning": False},
        }],
        "final_acceptance": ["Requested behavior"],
        "closure_matrix": {"schema_version": 3, "chains": [chain], "graph_receipt": {
            **receipt, "receipt_fingerprint": runner_fingerprint(receipt),
        }},
        "decisions": [], "checkpoint": "same_session",
    }


def closure_audit(plan):
    return {
        "plan": plan,
        "task_results": {"closure": {
            "status": "DONE", "source_before": SOURCE, "source_after": SOURCE,
            "fresh_pass": True, "evidence": [EVIDENCE],
        }},
        "final_acceptance": [{
            "criterion": "Requested behavior", "result": "pass", "freshness": "fresh",
            "evidence": EVIDENCE,
        }],
    }


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
        "baseline": {"commit": HEAD, "diff_fingerprint": SOURCE["diff_fingerprint"]},
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


def delegated_state(**overrides):
    value = state(**overrides)
    value["execution_control"]["routing"] = routing(task_profile(
        coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
    ))
    return value


def autonomous_state(**overrides):
    payload = state(schema_version=11)
    payload["execution_control"] = {
        **payload["execution_control"],
        "autonomy": {
            "schema_version": 1,
            "enabled": True,
            "manifest": {
                "source_fingerprint": SOURCE["source_fingerprint"],
                "items": [
                    {"id": "requirement", "kind": "requirement", "value": "Requested behavior"},
                    {"id": "scope", "kind": "scope", "value": "."},
                    {"id": "acceptance", "kind": "acceptance", "value": "Requested behavior"},
                ],
            },
            "audit_batches": [],
            "repair_budget_remaining": 1,
            "re_audit_budget_remaining": 1,
        },
    }
    payload.update(overrides)
    return payload


def committed_attempt():
    action_value = action("verify", task_id="task-123", phase="verify-final")
    return {
        "attempt_id": "attempt-1",
        "action": action_value,
        "status": "committed",
        "owner": "writer-123",
        "time_policy": {
            "startup_seconds": 10, "idle_seconds": 30,
            "absolute_seconds": 120, "max_extensions": 0,
        },
        "events": [{
            "kind": "started", "at": "2026-08-27T00:00:00Z",
            "evidence_fingerprint": "a" * 64,
        }],
        "observation": {"outcome": "completed", "receipt_fingerprint": "b" * 64},
        "commit": {
            "source_fingerprint": SOURCE["source_fingerprint"],
            "verification_fingerprint": "c" * 64,
        },
    }


def runtime_binding():
    observation = {
        "query_id": "capabilities-codex", "observed_at": "2026-08-21T00:00:00Z",
        "profile": "codex", "capabilities": ["dispatch", "query", "wait", "interrupt", "tree_query"],
    }
    return _bind("codex", "automatic", observation["capabilities"], "legacy test fixture",
                 "host_observed", observation)


def cleanup_receipt(binding, revision, registered_refs, active_refs, unexpected_refs, observed_at,
                    host_observation=None):
    """Legacy state fixture; production helpers cannot mint host observations."""
    return {
        "schema_version": 2, "observed_revision": revision, "observed_at": observed_at,
        "runtime_fingerprint": binding["binding_fingerprint"], "mode": "tree_query",
        "evidence_level": "host_observed", "observation_fingerprint": "a" * 64,
        "registered_refs": registered_refs, "active_refs": active_refs,
        "unexpected_refs": unexpected_refs,
    }


def desktop_binding():
    return negotiate(
        "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                  "tree_query": True, "restrict_dispatch": False}
    )


def reviewed_complete_state(*, reviewer_registered=False, quality_mode="blind",
                            integration_budget=0, integration_status=None,
                            integration_reviewer="reviewer-a", reviewer_ref="reviewer-a",
                            full_closure=False):
    payload = upgrade_state(state(
        status="complete", current_stage="verify-final", revision=3,
        runtime_binding=runtime_binding(),
    ))
    source = payload["source_fingerprint"]
    payload["execution_control"]["routing"]["review_tier"] = "normal"
    integration_required = integration_budget == 1 or integration_status is not None
    closure_request_text = "修复全部已知问题" if full_closure else ""
    payload["execution_control"]["routing"] = freeze_routing(task_profile(
        scope="cross-service" if integration_required else "cross-module",
        risk_flags=["cross-service"] if integration_required else [],
    ), ["."], request_text=closure_request_text, full_closure_required=full_closure)
    review = payload["execution_control"]["review"]
    review["integration_budget_remaining"] = integration_budget
    base = {
        "phase": "initial", "source_fingerprint": source, "status": "pass",
        "reviewer_ref": reviewer_ref, "finding_fingerprints": [],
        "finding_records": [], "task_id": payload["task_key"],
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
    if full_closure:
        requests.append({
            **base, "axis": "quality", "phase": "closure", "mode": "blind", "independent": True,
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
    else:
        reviewer_refs = [reviewer_ref]
    launches, results = [], []
    for index, record in enumerate(requests):
        request = {
            "protocol_version": 3, "task_id": payload["task_key"], "axis": record["axis"],
            "phase": record["phase"], "mode": record["mode"],
            "acceptance": ["Requested behavior"],
            "allowed_scope": payload["execution_control"]["routing"]["allowed_paths"],
            "baseline_commit": payload["baseline"]["commit"], "source_fingerprint": source,
            "prior_findings": [],
        }
        record["request_fingerprint"] = runner_fingerprint(request)
        reviewer_ref = record["reviewer_ref"]
        profile = {
            "schema_version": 1, "worker_id": reviewer_ref, "role": "reviewer",
            "runner_id": "openai-compatible-v1",
            "requested": {"model": "glm-5.2", "reasoning_effort": "high"},
            "effective": {"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
            "permissions": {"workspace": "read", "shell": False, "network": "egress"},
            "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 12000},
        }
        profile["profile_fingerprint"] = worker_profile_fingerprint(profile)
        launch = freeze_launch(profile, "Review", {
            "api_key_env": "GLM_API_KEY", "review_request_fingerprint": record["request_fingerprint"],
            "review_request": request,
        })
        receipt = {
            "schema_version": 1, "runner_id": "openai-compatible-v1",
            "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
            "response_id": f"review-{index + 1}", "response_model": "glm-5.2", "usage": None,
            "response_fingerprint": chr(ord("a") + index) * 64,
        }
        receipt["receipt_fingerprint"] = runner_fingerprint(receipt)
        launches.append(launch)
        results.append(bind_role_result(launch, receipt, review_result(launch, record)))
    payload["ledger"].update(runner_launches=launches, runner_results=results)
    if full_closure:
        closure = next(record for record in requests if record["phase"] == "closure")
        plan = closure_plan(payload["execution_control"]["routing"]["request_fingerprint"])
        payload["execution_control"]["closure"] = {
            "schema_version": 1, "status": "pass", "source_fingerprint": source,
            "scope_fingerprint": payload["execution_control"]["routing"]["profile_fingerprint"],
            "graph_receipt": graph_receipt(source, payload["execution_control"]["routing"], plan),
            "review_request_fingerprint": closure["request_fingerprint"],
            "plan": plan,
            "audit": closure_audit(plan),
        }
    return payload


class DeliveryNextTest(unittest.TestCase):
    def test_default_validator_import_does_not_load_autonomy_contract(self):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; sys.path.insert(0, 'scripts'); import delivery_next; "
                "print('autonomy_contract' in sys.modules)",
            ],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("False", result.stdout.strip())

    def test_autonomy_completion_rejects_an_uncommitted_action(self):
        autonomy = {
            "audit_batches": [{
                "source_fingerprint": "a" * 64, "phase": "initial", "status": "pass",
                "covered_manifest_ids": ["requirement", "scope", "acceptance"], "finding_fingerprints": [],
                "evidence_receipt_fingerprint": "b" * 64,
            }],
            "action_attempts": [{"status": "observed"}],
        }
        with self.assertRaisesRegex(ValueError, "committed"):
            validate_autonomy_completion(autonomy, "a" * 64, None, [])

    def test_autonomous_complete_requires_a_current_full_scope_audit(self):
        payload = autonomous_state(
            status="complete", current_stage="verify-final", revision=3,
        )

        with self.assertRaisesRegex(ValueError, "autonomy requires a current passing audit"):
            validate_state(payload, SimpleNamespace())

        payload["execution_control"]["autonomy"]["audit_batches"] = [{
            "source_fingerprint": SOURCE["source_fingerprint"], "phase": "initial",
            "status": "pass", "covered_manifest_ids": ["requirement", "scope", "acceptance"],
            "finding_fingerprints": [], "evidence_receipt_fingerprint": EVIDENCE["receipt_fingerprint"],
        }]
        payload["execution_control"]["autonomy"]["action_attempts"] = [committed_attempt()]
        payload["ledger"]["checks"].append({
            "stage": "autonomy-audit", "command": EVIDENCE["command"], "result": "pass",
            "evidence_receipts": [EVIDENCE],
        })
        self.assertEqual("complete", validate_state(payload, SimpleNamespace()))

    def test_autonomous_complete_requires_a_source_bound_audit_receipt(self):
        payload = autonomous_state(status="complete", current_stage="verify-final", revision=3)
        payload["execution_control"]["autonomy"]["audit_batches"] = [{
            "source_fingerprint": SOURCE["source_fingerprint"], "phase": "initial",
            "status": "pass", "covered_manifest_ids": ["requirement", "scope", "acceptance"],
            "finding_fingerprints": [], "evidence_receipt_fingerprint": EVIDENCE["receipt_fingerprint"],
        }]
        payload["execution_control"]["autonomy"]["action_attempts"] = [committed_attempt()]

        with self.assertRaisesRegex(ValueError, "audit Evidence Receipt"):
            validate_state(payload, SimpleNamespace())

    def test_autonomous_audit_cannot_claim_full_coverage_with_missing_manifest_item(self):
        payload = autonomous_state(
            status="complete", current_stage="verify-final", revision=3,
        )
        payload["execution_control"]["autonomy"]["audit_batches"] = [{
            "source_fingerprint": SOURCE["source_fingerprint"], "phase": "initial",
            "status": "pass", "covered_manifest_ids": ["requirement", "scope"],
            "finding_fingerprints": [], "evidence_receipt_fingerprint": EVIDENCE["receipt_fingerprint"],
        }]

        with self.assertRaisesRegex(ValueError, "coverage"):
            validate_state(payload, SimpleNamespace())

    def test_autonomous_completion_rejects_an_empty_action_history(self):
        payload = autonomous_state(status="complete", current_stage="verify-final", revision=3)
        payload["execution_control"]["autonomy"]["audit_batches"] = [{
            "source_fingerprint": SOURCE["source_fingerprint"], "phase": "initial",
            "status": "pass", "covered_manifest_ids": ["requirement", "scope", "acceptance"],
            "finding_fingerprints": [], "evidence_receipt_fingerprint": EVIDENCE["receipt_fingerprint"],
        }]
        payload["ledger"]["checks"].append({
            "stage": "autonomy-audit", "command": EVIDENCE["command"], "result": "pass",
            "evidence_receipts": [EVIDENCE],
        })

        with self.assertRaisesRegex(ValueError, "committed action"):
            validate_state(payload, SimpleNamespace())

    def test_autonomous_completion_rejects_an_audit_receipt_not_bound_to_its_batch(self):
        payload = autonomous_state(status="complete", current_stage="verify-final", revision=3)
        payload["execution_control"]["autonomy"]["action_attempts"] = [committed_attempt()]
        payload["execution_control"]["autonomy"]["audit_batches"] = [{
            "source_fingerprint": SOURCE["source_fingerprint"], "phase": "initial",
            "status": "pass", "covered_manifest_ids": ["requirement", "scope", "acceptance"],
            "finding_fingerprints": [], "evidence_receipt_fingerprint": "d" * 64,
        }]
        payload["ledger"]["checks"].append({
            "stage": "autonomy-audit", "command": EVIDENCE["command"], "result": "pass",
            "evidence_receipts": [EVIDENCE],
        })

        with self.assertRaisesRegex(ValueError, "bound audit Evidence Receipt"):
            validate_state(payload, SimpleNamespace())

    def test_autonomous_manifest_cannot_omit_requirement_or_acceptance(self):
        payload = autonomous_state()
        payload["execution_control"]["autonomy"]["manifest"]["items"] = [
            {"id": "scope", "kind": "scope", "value": "."},
        ]

        with self.assertRaisesRegex(ValueError, "requirement, scope, and acceptance"):
            validate_state(payload, SimpleNamespace())

    def test_caller_cannot_override_the_canonical_profile_route(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"]["route"] = "batch"

        with self.assertRaisesRegex(ValueError, "canonical task profile"):
            validate_state(payload, SimpleNamespace())

    def test_caller_cannot_drop_a_frozen_full_closure_requirement(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = freeze_routing(
            task_profile(), ["."], request_text="修复全部已知问题", full_closure_required=True,
        )
        payload["execution_control"]["routing"]["full_closure_required"] = False

        with self.assertRaisesRegex(ValueError, "canonical task profile"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_route_requires_one_explicit_pending_or_terminal_gate(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = freeze_routing(
            task_profile(), ["."], request_text="彻底检查并修复全部已知问题",
            full_closure_required=True,
        )

        with self.assertRaisesRegex(ValueError, "closure gate"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_complete_requires_a_current_passing_gate(self):
        payload = reviewed_complete_state()
        routing_value = freeze_routing(
            task_profile(scope="cross-module"), ["."], request_text="修复全部已知问题",
            full_closure_required=True,
        )
        payload["execution_control"]["routing"] = routing_value
        payload["execution_control"]["closure"] = {
            "schema_version": 1, "status": "pending", "source_fingerprint": None,
            "scope_fingerprint": routing_value["profile_fingerprint"],
            "graph_receipt": None, "review_request_fingerprint": None,
            "plan": closure_plan(routing_value["request_fingerprint"]), "audit": None,
        }

        with self.assertRaisesRegex(ValueError, "current passing closure gate"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_gate_requires_one_current_independent_closure_review(self):
        payload = reviewed_complete_state()
        routing_value = freeze_routing(
            task_profile(scope="cross-module"), ["."], request_text="修复全部已知问题",
            full_closure_required=True,
        )
        payload["execution_control"]["routing"] = routing_value
        plan = closure_plan(routing_value["request_fingerprint"])
        payload["execution_control"]["closure"] = {
            "schema_version": 1, "status": "pass",
            "source_fingerprint": payload["source_fingerprint"],
            "scope_fingerprint": routing_value["profile_fingerprint"],
            "graph_receipt": graph_receipt(payload["source_fingerprint"], routing_value, plan),
            "review_request_fingerprint": "b" * 64,
            "plan": plan, "audit": None,
        }

        with self.assertRaisesRegex(ValueError, "closure review"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_can_complete_with_one_bound_independent_closure_review(self):
        payload = reviewed_complete_state(full_closure=True)

        self.assertEqual("complete", validate_state(payload, SimpleNamespace()))

    def test_full_closure_requires_a_plan_v6(self):
        payload = reviewed_complete_state(full_closure=True)
        del payload["execution_control"]["closure"]["plan"]

        with self.assertRaisesRegex(ValueError, "closure gate fields are invalid"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_rejects_a_plan_for_another_request(self):
        payload = reviewed_complete_state(full_closure=True)
        payload["execution_control"]["closure"]["plan"]["requirement_fingerprint"] = "b" * 64

        with self.assertRaisesRegex(ValueError, "closure plan requirement"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_rejects_a_plan_task_with_a_different_provider_binding(self):
        payload = reviewed_complete_state(full_closure=True)
        payload["execution_control"]["closure"]["plan"]["tasks"][0]["provider_binding"]["selection"] = "explicit"

        with self.assertRaisesRegex(ValueError, "closure plan provider binding"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_rejects_a_plan_with_a_different_baseline_diff(self):
        payload = reviewed_complete_state(full_closure=True)
        plan = payload["execution_control"]["closure"]["plan"]
        source = plan["baseline"]["source"]
        source["diff_fingerprint"] = "b" * 64
        source["source_fingerprint"] = hashlib.sha256(json.dumps(
            {key: value for key, value in source.items() if key != "source_fingerprint"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        receipt = plan["closure_matrix"]["graph_receipt"]
        receipt["source_fingerprint"] = source["source_fingerprint"]
        receipt["receipt_fingerprint"] = runner_fingerprint({
            key: value for key, value in receipt.items() if key != "receipt_fingerprint"
        })

        with self.assertRaisesRegex(ValueError, "closure plan baseline source"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_rejects_a_matrix_narrower_than_the_frozen_scope(self):
        payload = reviewed_complete_state(full_closure=True)
        plan = payload["execution_control"]["closure"]["plan"]
        plan["closure_matrix"]["chains"][0]["entrypoints"] = ["scripts/test_delivery_next.py"]
        receipt = plan["closure_matrix"]["graph_receipt"]
        receipt["chains_fingerprint"] = hashlib.sha256(json.dumps([{
            "id": "main", "entrypoints": ["scripts/test_delivery_next.py"], "callers": ["external"],
        }], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        receipt["receipt_fingerprint"] = runner_fingerprint({
            key: value for key, value in receipt.items() if key != "receipt_fingerprint"
        })

        with self.assertRaisesRegex(ValueError, "closure plan matrix does not cover frozen scope"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_rejects_a_plan_task_outside_the_frozen_scope(self):
        routing_value = routing(allowed_paths=["scripts"])
        plan = closure_plan(routing_value["request_fingerprint"])

        with self.assertRaisesRegex(ValueError, "closure plan task scope exceeds frozen routing"):
            validate_closure_plan(
                plan, routing_value,
                {"commit": HEAD, "diff_fingerprint": SOURCE["diff_fingerprint"]},
                state()["provider_binding"],
            )

    def test_full_closure_complete_requires_a_passing_plan_audit(self):
        payload = reviewed_complete_state(full_closure=True)
        payload["execution_control"]["closure"]["audit"] = None

        with self.assertRaisesRegex(ValueError, "complete state requires a passing closure plan audit"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_rejects_a_tampered_graph_receipt(self):
        payload = reviewed_complete_state(full_closure=True)
        closure = payload["execution_control"]["closure"]
        closure["graph_receipt"]["output_fingerprint"] = "b" * 64

        with self.assertRaisesRegex(ValueError, "graph receipt"):
            validate_closure_gate(
                closure, payload["source_fingerprint"], payload["source_receipt"],
                payload["execution_control"]["routing"], payload["baseline"],
                payload["provider_binding"],
            )

    def test_full_closure_rejects_an_unverified_codebase_memory_graph_receipt(self):
        payload = reviewed_complete_state(full_closure=True)
        closure = payload["execution_control"]["closure"]
        closure["graph_receipt"] = graph_receipt(
            payload["source_fingerprint"],
            payload["execution_control"]["routing"], closure["plan"], tool="codebase-memory-mcp",
        )

        with self.assertRaisesRegex(ValueError, "graph receipt"):
            validate_closure_gate(
                closure, payload["source_fingerprint"], payload["source_receipt"],
                payload["execution_control"]["routing"], payload["baseline"],
                payload["provider_binding"],
            )

    def test_full_closure_rejects_a_codegraph_version_receipt(self):
        payload = reviewed_complete_state(full_closure=True)
        closure = payload["execution_control"]["closure"]
        graph = closure["graph_receipt"]
        evidence = graph["evidence"]
        evidence["argv"] = ["codegraph", "--version"]
        evidence["command"] = shlex.join(evidence["argv"])
        evidence["receipt_fingerprint"] = runner_fingerprint({
            key: value for key, value in evidence.items() if key != "receipt_fingerprint"
        })
        graph["receipt_fingerprint"] = runner_fingerprint({
            key: value for key, value in graph.items() if key != "receipt_fingerprint"
        })

        with self.assertRaisesRegex(ValueError, "graph-tool query"):
            validate_closure_gate(
                closure, payload["source_fingerprint"], payload["source_receipt"],
                payload["execution_control"]["routing"], payload["baseline"],
                payload["provider_binding"],
            )

    def test_full_closure_rejects_an_unrelated_codegraph_query(self):
        payload = reviewed_complete_state(full_closure=True)
        closure = payload["execution_control"]["closure"]
        closure["graph_receipt"] = graph_receipt(
            payload["source_fingerprint"], payload["execution_control"]["routing"], closure["plan"],
            query="unrelated query",
        )

        with self.assertRaisesRegex(ValueError, "graph-tool query"):
            validate_closure_gate(
                closure, payload["source_fingerprint"], payload["source_receipt"],
                payload["execution_control"]["routing"], payload["baseline"],
                payload["provider_binding"],
            )

    def test_full_closure_rejects_an_unknown_graph_receipt_tool(self):
        payload = reviewed_complete_state(full_closure=True)
        closure = payload["execution_control"]["closure"]
        closure["graph_receipt"] = graph_receipt(
            payload["source_fingerprint"],
            payload["execution_control"]["routing"], closure["plan"], tool="unknown-graph",
        )

        with self.assertRaisesRegex(ValueError, "graph receipt"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_rejects_a_third_review_instead_of_looping(self):
        payload = reviewed_complete_state(full_closure=True)
        closure = next(
            record for record in payload["execution_control"]["review"]["rounds"][0]["requests"]
            if record["phase"] == "closure"
        )
        payload["execution_control"]["review"]["rounds"][0]["requests"].extend([
            dict(closure), dict(closure),
        ])

        with self.assertRaisesRegex(ValueError, "closure review budget"):
            validate_state(payload, SimpleNamespace())

    def test_full_closure_routes_final_verification_to_one_closure_review(self):
        payload = state(current_stage="verify-final")
        routing_value = freeze_routing(
            task_profile(), ["."], request_text="彻底检查所有问题", full_closure_required=True,
        )
        payload["execution_control"]["routing"] = routing_value
        payload["execution_control"]["closure"] = {
            "schema_version": 1, "status": "pending", "source_fingerprint": None,
            "scope_fingerprint": routing_value["profile_fingerprint"],
            "graph_receipt": None, "review_request_fingerprint": None,
            "plan": closure_plan(routing_value["request_fingerprint"]), "audit": None,
        }

        self.assertEqual("closure-review", validate_state(payload, SimpleNamespace()))

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
                "schema_version": 1, "worker_id": "scout-1", "role": "scout",
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

    def test_complete_review_pass_requires_the_completed_reviewer_result(self):
        payload = reviewed_complete_state()
        payload["ledger"].pop("runner_launches")
        payload["ledger"].pop("runner_results")

        with self.assertRaisesRegex(ValueError, "reviewer result"):
            validate_state(payload, SimpleNamespace())

    def test_complete_review_pass_requires_a_result_bound_to_its_frozen_request(self):
        payload = reviewed_complete_state()
        configuration = payload["ledger"]["runner_launches"][0]["configuration"]
        configuration["review_request"] = {
            **configuration["review_request"], "acceptance": ["Different requirement"],
        }
        configuration["review_request_fingerprint"] = runner_fingerprint(configuration["review_request"])
        launch = payload["ledger"]["runner_launches"][0]
        launch["launch_fingerprint"] = runner_fingerprint({
            key: value for key, value in launch.items() if key != "launch_fingerprint"
        })
        result = payload["ledger"]["runner_results"][0]
        result["launch_fingerprint"] = launch["launch_fingerprint"]
        result["role_result"]["launch_fingerprint"] = launch["launch_fingerprint"]
        role_result = result["role_result"]
        role_result["result_fingerprint"] = runner_fingerprint({
            key: value for key, value in role_result.items() if key != "result_fingerprint"
        })
        result["receipt_fingerprint"] = runner_fingerprint({
            key: value for key, value in result.items() if key != "receipt_fingerprint"
        })

        with self.assertRaisesRegex(ValueError, "bound to its request"):
            validate_state(payload, SimpleNamespace())

    def test_complete_review_pass_revalidates_external_request_scope_and_acceptance(self):
        payload = reviewed_complete_state()
        launch = payload["ledger"]["runner_launches"][0]
        configuration = launch["configuration"]
        request = {**configuration["review_request"], "acceptance": ["Different requirement"]}
        request_fingerprint = runner_fingerprint(request)
        configuration.update(review_request=request, review_request_fingerprint=request_fingerprint)
        record = payload["execution_control"]["review"]["rounds"][0]["requests"][0]
        record["request_fingerprint"] = request_fingerprint
        launch["launch_fingerprint"] = runner_fingerprint({
            key: value for key, value in launch.items() if key != "launch_fingerprint"
        })
        result = payload["ledger"]["runner_results"][0]
        result["launch_fingerprint"] = launch["launch_fingerprint"]
        role_result = result["role_result"]
        role_result["launch_fingerprint"] = launch["launch_fingerprint"]
        role_result["review_record"] = record
        role_result["result_fingerprint"] = runner_fingerprint({
            key: value for key, value in role_result.items() if key != "result_fingerprint"
        })
        result["receipt_fingerprint"] = runner_fingerprint({
            key: value for key, value in result.items() if key != "receipt_fingerprint"
        })

        with self.assertRaisesRegex(ValueError, "bound to its request"):
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
            output_format=overrides.get("output_format", "legacy"),
        )

    def test_low_risk_semantic_review_moves_to_final_verification(self):
        result = self.current()

        self.assertEqual("verify-final\n", result.stdout)
        self.assertEqual(0, result.returncode)

    def test_rejects_unknown_state_fields(self):
        payload = delegated_state()
        payload["native_handoff"] = {}

        result = self.current(payload, output_format="json")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("state fields", result.stderr)

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

    def test_blocked_state_prioritizes_its_terminal_action_over_pending_host_sync(self):
        payload = delegated_state(
            status="blocked", blocked_code="no_progress",
            blocked_reason="manual reconciliation is required",
        )
        payload["host_sync"] = {
            "mode": "native", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        }

        result = self.current(payload, output_format="json")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            {"action": "block", "task_id": "task-123", "reason": "manual reconciliation is required"},
            json.loads(result.stdout),
        )

    def test_complete_state_can_still_finish_a_pending_host_sync(self):
        payload = state(status="complete", current_stage="verify-final")
        payload["host_sync"] = {
            "mode": "native", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        }

        result = self.current(payload, output_format="json")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("sync-plan", json.loads(result.stdout)["action"])

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
            "depth": 1, "may_dispatch": False, "role": "implementer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("task", result.stderr)

    def test_active_workers_require_frozen_delegation_or_reviewer_exemption(self):
        payload = upgrade_state(state())
        payload["runtime_binding"] = desktop_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "implementer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "frozen route"):
            validate_state(payload, SimpleNamespace())

    def test_worker_role_must_be_a_known_host_worker_role(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
        ))
        payload["runtime_binding"] = desktop_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "unrecognized",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "role"):
            validate_state(payload, SimpleNamespace())

    def test_worker_legacy_role_aliases_are_rejected(self):
        for role in ("implementation", "review"):
            with self.subTest(role=role):
                payload = upgrade_state(state())
                payload["execution_control"]["routing"] = routing(task_profile(
                    coupling="independent", delegable_tasks=1,
                    context_isolation_benefit=True,
                ))
                payload["runtime_binding"] = desktop_binding()
                payload["workers"] = [{
                    "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
                    "depth": 1, "may_dispatch": False, "role": role,
                    "owner_run_id": payload["run_id"], "status": "working", "progress": None,
                }]

                with self.assertRaisesRegex(ValueError, "role"):
                    validate_state(payload, SimpleNamespace())

    def test_inline_route_rejects_low_risk_reviewer_and_host_only_roles(self):
        for role in ("pdlc", "evaluator", "controller-delegate"):
            with self.subTest(role=role):
                payload = upgrade_state(state())
                payload["runtime_binding"] = desktop_binding()
                payload["workers"] = [{
                    "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
                    "depth": 1, "may_dispatch": False, "role": role,
                    "owner_run_id": payload["run_id"], "status": "working", "progress": None,
                }]

                with self.assertRaisesRegex(ValueError, "frozen route"):
                    validate_state(payload, SimpleNamespace())

    def test_active_worker_rejects_a_controller_attested_codex_binding(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
        ))
        payload["runtime_binding"] = desktop_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "implementer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "host-observed"):
            validate_state(payload, SimpleNamespace())

    def test_delegated_worker_rejects_a_controller_attested_codex_binding(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
        ))
        payload["runtime_binding"] = desktop_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "implementer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "host-observed"):
            validate_state(payload, SimpleNamespace())

    def test_active_worker_rejects_a_controller_attested_claude_code_binding(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
        ))
        payload["runtime_binding"] = negotiate(
            "claude-code", {"dispatch": True, "query": True, "tree_query": True}
        )
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "implementer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "host-observed"):
            validate_state(payload, SimpleNamespace())

    def test_cross_session_worker_requires_a_host_observed_binding(self):
        payload = upgrade_state(state())
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
            cross_session=True,
        ))
        payload["runtime_binding"] = desktop_binding()
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "implementer",
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

    def test_complete_with_workers_requires_a_concrete_host_bridge(self):
        payload = reviewed_complete_state()
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
        ))
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "implementer",
            "owner_run_id": payload["run_id"], "status": "completed", "progress": None,
        }]
        payload["worker_tree_receipt"] = None

        missing = self.current(payload, revision=3)
        self.assertNotEqual(0, missing.returncode)
        self.assertIn("host-observed tree-query runtime", missing.stderr)

        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, ["worker-1"], [], ["nested-worker"],
            "2026-08-21T00:00:00Z", host_observation={
                "query_id": "query-unexpected", "observed_at": "2026-08-21T00:00:00Z",
                "registered_refs": ["worker-1"], "active_refs": [],
                "unexpected_refs": ["nested-worker"],
            },
        )
        unexpected = self.current(payload, revision=3)
        self.assertNotEqual(0, unexpected.returncode)
        self.assertIn("host-observed tree-query runtime", unexpected.stderr)

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
        self.assertNotEqual(0, clean.returncode)
        self.assertIn("host-observed tree-query runtime", clean.stderr)

    def test_complete_rejects_unexpected_descendants_even_with_empty_registry(self):
        payload = upgrade_state(state(
            status="complete", current_stage="verify-final", revision=3,
            runtime_binding=runtime_binding(),
        ))
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, [], [], ["unregistered-worker"],
            "2026-08-21T00:00:00Z", host_observation={
                "query_id": "query-unexpected", "observed_at": "2026-08-21T00:00:00Z",
                "registered_refs": [], "active_refs": [],
                "unexpected_refs": ["unregistered-worker"],
            },
        )

        result = self.current(payload, revision=3)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unexpected", result.stderr)

    def test_active_unexpected_descendant_requires_blocked_state(self):
        payload = upgrade_state(state(revision=3, runtime_binding=runtime_binding()))
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, [], [], ["unregistered-worker"],
            "2026-08-21T00:00:00Z", host_observation={
                "query_id": "query-unexpected", "observed_at": "2026-08-21T00:00:00Z",
                "registered_refs": [], "active_refs": [],
                "unexpected_refs": ["unregistered-worker"],
            },
        )

        with self.assertRaisesRegex(ValueError, "unexpected workers require blocked state"):
            validate_state(payload, SimpleNamespace())

        payload.update(
            status="blocked", blocked_code="environment",
            blocked_reason="unregistered worker requires manual cleanup",
        )
        self.assertEqual("blocked", validate_state(payload, SimpleNamespace()))

    def test_complete_with_workers_rejects_controller_attested_codex_cleanup(self):
        payload = reviewed_complete_state()
        payload["runtime_binding"] = desktop_binding()
        refs = [worker["ref"] for worker in payload["workers"]]
        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
            runtime_cleanup_receipt(payload["runtime_binding"], 3, refs, [], [], "2026-08-21T00:00:00Z")

    def test_complete_rejects_direct_controller_attested_cleanup_receipt(self):
        payload = reviewed_complete_state()
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
        ))
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "implementer",
            "owner_run_id": payload["run_id"], "status": "completed", "progress": None,
        }]
        payload["worker_tree_receipt"] = {
            "schema_version": 2, "observed_revision": 3,
            "observed_at": "2026-08-21T00:00:00Z",
            "runtime_fingerprint": payload["runtime_binding"]["binding_fingerprint"],
            "mode": "tree_query", "evidence_level": "controller_attested",
            "observation_fingerprint": None, "registered_refs": ["worker-1"],
            "active_refs": [], "unexpected_refs": [],
        }

        result = self.current(payload, revision=3)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("host-observed", result.stderr)

    def test_high_risk_complete_requires_current_spec_and_quality_reviews(self):
        payload = state(status="complete", current_stage="verify-final")
        payload["execution_control"]["routing"] = routing(
            task_profile(risk_flags=["money"])
        )

        result = self.current(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("review", result.stderr)

    def test_normal_review_accepts_a_completed_external_reviewer(self):
        payload = reviewed_complete_state(
            reviewer_registered=False, reviewer_ref="reviewer-1",
        )

        self.assertEqual("complete", validate_state(payload, SimpleNamespace()))

    def test_normal_review_rejects_a_native_registered_reviewer(self):
        payload = reviewed_complete_state()
        payload["workers"] = [{
            "ref": "reviewer-a", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "completed", "progress": None,
        }]

        with self.assertRaisesRegex(ValueError, "external runner"):
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
        payload["execution_control"]["review"]["rounds"][0]["requests"][-1][
            "finding_records"
        ] = [{
            "fingerprint": "d" * 64, "evidence": "integration check failed",
            "impact": "cross-service behavior is not verified",
            "root_cause": "pending repair", "scope": "current",
            "classification": "defect",
        }]
        result = payload["ledger"]["runner_results"][-1]
        role_result = result["role_result"]
        role_result["review_record"] = payload["execution_control"]["review"]["rounds"][0]["requests"][-1]
        role_result["result_fingerprint"] = runner_fingerprint({
            key: value for key, value in role_result.items() if key != "result_fingerprint"
        })
        result["receipt_fingerprint"] = runner_fingerprint({
            key: value for key, value in result.items() if key != "receipt_fingerprint"
        })

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

    def test_current_review_round_rejects_findings_without_structured_records(self):
        control = state()["execution_control"]
        source = control["review"]["rounds"][0]["source_fingerprint"]
        control["review"]["rounds"][0]["requests"] = [{
            "axis": "spec", "phase": "initial", "source_fingerprint": source,
            "status": "findings", "reviewer_ref": "reviewer-a", "mode": "shared",
            "independent": False, "finding_fingerprints": ["b" * 64],
            "task_id": "task-123", "request_fingerprint": "c" * 64,
        }]

        with self.assertRaisesRegex(ValueError, "current review findings require finding_records"):
            validate_execution_control(control, source, "task-123")

    def test_blocked_with_active_worker_requires_fresh_cleanup_receipt(self):
        worker = {
            "ref": "worker-1", "parent_ref": None, "task_id": "task-123",
            "depth": 1, "may_dispatch": False,
            "role": "implementer",
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
        payload["execution_control"]["routing"] = routing(task_profile(
            coupling="independent", delegable_tasks=1, context_isolation_benefit=True,
        ))
        payload["workers"] = [worker]
        payload = upgrade_state(payload)

        missing = self.current(payload, revision=4)
        self.assertNotEqual(0, missing.returncode)
        self.assertIn("cleanup receipt", missing.stderr)

        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 4, ["worker-1"], ["worker-1"], [],
            "2026-08-21T00:00:00Z", host_observation={
                "query_id": "query-active", "observed_at": "2026-08-21T00:00:00Z",
                "registered_refs": ["worker-1"], "active_refs": ["worker-1"],
                "unexpected_refs": [],
            },
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

    def test_active_final_verification_state_selects_its_frozen_final_action(self):
        result = self.current(state(current_stage="verify-final"))

        self.assertEqual("verify-final\n", result.stdout)
        self.assertEqual(0, result.returncode)

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
