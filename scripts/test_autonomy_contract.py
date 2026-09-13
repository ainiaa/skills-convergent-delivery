#!/usr/bin/env python3
"""Behavior tests for the optional autonomous-delivery state extension."""

import unittest

from autonomy_contract import validate_action_attempts, validate_autonomy
from worker_profile import fingerprint as profile_fingerprint


SHA = "a" * 64


def routing(**overrides):
    value = {"allowed_paths": ["src/payment"], "review_tier": "normal"}
    value.update(overrides)
    return value


def manifest_items():
    return [
        {"id": "requirement-1", "kind": "requirement", "value": "complete the frozen task"},
        {"id": "scope-1", "kind": "scope", "value": "src/payment"},
        {"id": "acceptance-1", "kind": "acceptance", "value": "targeted tests pass"},
    ]


def autonomy(**overrides):
    value = {
        "schema_version": 1, "enabled": True,
        "manifest": {"source_fingerprint": SHA, "items": manifest_items()},
        "audit_batches": [],
        "repair_budget_remaining": 1, "re_audit_budget_remaining": 1,
        "runtime": {"mode": "hook"},
        "action_attempts": [],
    }
    value.update(overrides)
    return value


def attempt(**overrides):
    value = {
        "attempt_id": "hook-0",
        "action": {"action": "execute-inline", "task_id": "T1", "phase": "implementation"},
        "status": "intent",
        "owner": "writer-1",
        "time_policy": {
            "startup_seconds": 1, "idle_seconds": 30, "absolute_seconds": 300, "max_extensions": 0,
        },
        "events": [],
        "observation": None,
        "commit": None,
    }
    value.update(overrides)
    return value


def batch(**overrides):
    value = {
        "source_fingerprint": SHA, "phase": "initial", "status": "findings",
        "covered_manifest_ids": ["requirement-1", "scope-1", "acceptance-1"],
        "finding_fingerprints": ["b" * 64],
        "evidence_receipt_fingerprint": "c" * 64,
    }
    value.update(overrides)
    return value


def implementer_profile(**overrides):
    value = {
        "schema_version": 1, "worker_id": "implementer-1", "role": "implementer",
        "runner_id": "codex-exec-v1",
        "requested": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "effective": {"provider": "openai", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "permissions": {"workspace": "write", "shell": True, "network": "egress"},
        "budget": {"max_turns": 2, "timeout_seconds": 180, "max_output_chars": 12000},
    }
    value.update(overrides)
    identity = {key: item for key, item in value.items() if key != "profile_fingerprint"}
    return {**identity, "profile_fingerprint": profile_fingerprint(identity)}


class AutonomyContractTest(unittest.TestCase):
    def test_action_attempts_accept_one_intent_and_reject_malformed_inputs(self):
        self.assertEqual([attempt()], validate_action_attempts([attempt()]))

        with self.assertRaisesRegex(ValueError, "attempts are invalid"):
            validate_action_attempts("intent")
        with self.assertRaisesRegex(ValueError, "action attempt action is invalid"):
            validate_action_attempts([attempt(action={
                "action": "execute-inline", "task_id": "T1", "phase": "implementation",
                "reason": None,
            })])
        with self.assertRaisesRegex(ValueError, "time policy is invalid"):
            validate_action_attempts([attempt(time_policy={
                "startup_seconds": True, "idle_seconds": 30, "absolute_seconds": 300,
                "max_extensions": 0,
            })])

    def test_runtime_must_be_a_known_hook_or_service_shape(self):
        with self.assertRaisesRegex(ValueError, "service runtime is invalid"):
            validate_autonomy(autonomy(runtime={
                "mode": "service", "runner_profile": implementer_profile(), "max_cycles": 0,
                "verification_argv": ["true"], "audit_argv": ["python3", "-c", "pass"],
            }), SHA, routing())
        with self.assertRaisesRegex(ValueError, "runtime is invalid"):
            validate_autonomy(autonomy(runtime={"mode": "bogus"}), SHA, routing())

    def test_manifest_must_bind_unique_well_formed_scope_items(self):
        with self.assertRaisesRegex(ValueError, "manifest fields are invalid"):
            validate_autonomy(autonomy(manifest={"source_fingerprint": SHA}), SHA, routing())
        with self.assertRaisesRegex(ValueError, "item fields are invalid"):
            validate_autonomy(autonomy(manifest={
                "source_fingerprint": SHA, "items": [{"id": "requirement-1"}],
            }), SHA, routing())
        with self.assertRaisesRegex(ValueError, "manifest item is invalid"):
            validate_autonomy(autonomy(manifest={
                "source_fingerprint": SHA,
                "items": [{**manifest_items()[0], "kind": "note"}, *manifest_items()[1:]],
            }), SHA, routing())
        with self.assertRaisesRegex(ValueError, "item ids are invalid"):
            validate_autonomy(autonomy(manifest={
                "source_fingerprint": SHA,
                "items": [*manifest_items(), manifest_items()[0]],
            }), SHA, routing())

    def test_audit_batches_must_be_well_formed_and_budgeted(self):
        with self.assertRaisesRegex(ValueError, "audit batches are invalid"):
            validate_autonomy(autonomy(audit_batches="none"), SHA, routing())
        with self.assertRaisesRegex(ValueError, "audit batch is invalid"):
            validate_autonomy(autonomy(audit_batches=[batch(phase="weird")]), SHA, routing())
        with self.assertRaisesRegex(ValueError, "audit coverage is invalid"):
            validate_autonomy(autonomy(audit_batches=[
                batch(covered_manifest_ids=["unknown-id"]),
            ]), SHA, routing())
        with self.assertRaisesRegex(ValueError, "findings are invalid"):
            validate_autonomy(autonomy(audit_batches=[
                batch(finding_fingerprints=["b" * 64, "b" * 64]),
            ]), SHA, routing())
        with self.assertRaisesRegex(ValueError, "findings require fingerprints"):
            validate_autonomy(autonomy(audit_batches=[
                batch(finding_fingerprints=[]),
            ]), SHA, routing())
        with self.assertRaisesRegex(ValueError, "re_audit requires"):
            validate_autonomy(autonomy(audit_batches=[
                batch(), batch(phase="re_audit", status="pass", finding_fingerprints=[]),
            ]), SHA, routing())
        with self.assertRaisesRegex(ValueError, "must consume both budgets"):
            validate_autonomy(autonomy(audit_batches=[
                batch(),
                batch(source_fingerprint="d" * 64, phase="re_audit", status="pass",
                      finding_fingerprints=[]),
            ]), SHA, routing())

    def test_one_completed_repair_cycle_with_both_budgets_spent_is_valid(self):
        value = autonomy(
            repair_budget_remaining=0, re_audit_budget_remaining=0,
            audit_batches=[
                batch(),
                batch(source_fingerprint="d" * 64, phase="re_audit", status="pass",
                      finding_fingerprints=[]),
            ],
        )

        self.assertEqual(value, validate_autonomy(value, SHA, routing()))


if __name__ == "__main__":
    unittest.main()
