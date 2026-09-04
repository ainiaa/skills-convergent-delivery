#!/usr/bin/env python3
"""Cross-helper lifecycle scenarios using only production contracts."""

import copy
import unittest
from types import SimpleNamespace

from delivery_engine import controller_identity, provider_reference
from delivery_next import validate_state
from delivery_report import build_report
from delivery_state import validate_transition
from autonomy_gate import decide as autonomy_decide
from provider_contract import canonical_fingerprint
from run_contract import action
from runtime_adapter import bind_observed, cleanup_receipt
from task_profile import classify, freeze_routing


def profile(**overrides):
    value = {
        "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
        "coupling": "single", "uncertainty": "low", "verification": "local",
        "risk_flags": [], "cross_session": False, "delegable_tasks": 0,
        "context_isolation_benefit": False,
    }
    value.update(overrides)
    return value


def blocked_worker_state():
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference("native-v1", "fix"),
        "stage_providers": {},
    }
    runtime = bind_observed("codex", {
        "query_id": "capabilities-runtime", "observed_at": "2026-08-21T00:00:00Z",
        "profile": "codex", "capabilities": ["dispatch", "query", "wait", "interrupt", "tree_query"],
    })
    value = {
        "schema_version": 10,
        "run_id": "run-runtime", "repo_id": "/repo/common.git", "task_key": "T1",
        "writer_id": "writer-runtime", "revision": 0, "workspace": "/repo/worktree",
        "baseline": {"commit": "abc123", "diff_fingerprint": "clean"},
        "scope_fingerprint": "scope-runtime", "controller": controller_identity(),
        "source_fingerprint": "a" * 64,
        "source_receipt": None,
        "host_sync": {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        },
        "execution_control": {
            "routing": freeze_routing(profile(
                scope="cross-module", coupling="independent", delegable_tasks=1,
                context_isolation_benefit=True,
            ), ["."]),
            "review": {
                "protocol_version": 3,
                "repair_budget_remaining": 1, "re_review_budget_remaining": 1,
                "integration_budget_remaining": 0, "rounds": [],
            },
        },
        "provider_binding": {
            "selection": "auto", "reason": "native fallback", "task_kind": "fix",
            "binding": binding, "binding_fingerprint": canonical_fingerprint(binding),
        },
        "runtime_binding": runtime, "current_stage": "scope",
        "requires_stability_round": False, "status": "blocked",
        "blocked_code": "environment", "blocked_reason": "worker cleanup required",
        "workers": [{
            "ref": "worker-1", "parent_ref": None, "task_id": "T1", "depth": 1,
            "may_dispatch": False, "role": "pdlc", "owner_run_id": "run-runtime",
            "status": "working", "progress": None,
        }],
        "ledger": {
            "completed_rounds": 0, "repair_fingerprints": [], "key_changes": [],
            "checks": [], "acceptance": [{
                "criterion": "cleanup is recorded", "evidence": "host query",
                "result": "unknown", "freshness": "unavailable",
                "source_fingerprint": "a" * 64,
            }], "acceptance_history": [],
        },
        "handoff": {
            "goal": "close the worker", "last_verification": "host still working",
            "open_issues": ["worker-1"], "next_action": "interrupt worker-1",
        },
    }
    value["worker_tree_receipt"] = cleanup_receipt(
        runtime, 0, ["worker-1"], ["worker-1"], [], "2026-08-21T00:00:00Z",
        host_observation={
            "query_id": "query-working", "observed_at": "2026-08-21T00:00:00Z",
            "registered_refs": ["worker-1"], "active_refs": ["worker-1"], "unexpected_refs": [],
        },
    )
    return value


class RuntimeScenarioTest(unittest.TestCase):

    def test_autonomous_gate_to_terminal_report_uses_one_state_derived_path(self):
        from test_autonomy_gate import completed_state

        completed = completed_state()
        self.assertEqual({"decision": "allow", "terminal": "complete"}, autonomy_decide(completed))
        self.assertEqual("pass", build_report(completed)["autonomy_audit"]["status"])

        blocked = copy.deepcopy(completed)
        blocked.update(status="blocked", blocked_code="decision", blocked_reason="approval required")
        blocked["ledger"]["acceptance"][0].update(result="unknown", freshness="unavailable")
        self.assertEqual({"decision": "allow", "terminal": "blocked"}, autonomy_decide(blocked))
        self.assertEqual("decision", build_report(blocked)["outcome"])

    def test_legacy_state_is_not_silently_armed_for_autonomy(self):
        from test_delivery_next import state

        self.assertEqual({"decision": "allow", "terminal": "inactive"}, autonomy_decide(state()))

    def test_provisional_cross_session_work_cannot_dispatch(self):
        decision = classify(profile(assessment_phase="provisional", cross_session=True))
        self.assertEqual("planned", decision["route"])
        self.assertEqual("batch", decision["recommended_route"])

    def test_frozen_cross_session_work_dispatches_with_task_identity(self):
        decision = classify(profile(cross_session=True))
        self.assertEqual("batch", decision["route"])
        self.assertEqual({"action": "dispatch", "task_id": "T1"}, action("dispatch", task_id="T1"))

    def test_frozen_local_work_stays_inline(self):
        self.assertEqual("inline", classify(profile())["route"])
        self.assertEqual(
            {"action": "execute-inline", "task_id": "T1", "phase": "build"},
            action("execute-inline", task_id="T1", phase="build"),
        )

    def test_blocked_worker_cleanup_can_reach_a_recorded_host_terminal_state(self):
        previous = blocked_worker_state()
        self.assertEqual("blocked", validate_state(previous, SimpleNamespace()))
        candidate = copy.deepcopy(previous)
        candidate["revision"] = 1
        candidate["workers"][0]["status"] = "interrupted"
        candidate["worker_tree_receipt"] = cleanup_receipt(
            candidate["runtime_binding"], 1, ["worker-1"], [], [],
            "2026-08-21T00:01:00Z", host_observation={
                "query_id": "query-clean", "observed_at": "2026-08-21T00:01:00Z",
                "registered_refs": ["worker-1"], "active_refs": [], "unexpected_refs": [],
            },
        )
        self.assertEqual("blocked", validate_state(candidate, SimpleNamespace()))
        validate_transition(previous, candidate)


if __name__ == "__main__":
    unittest.main()
