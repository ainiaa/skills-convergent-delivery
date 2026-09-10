#!/usr/bin/env python3
"""Behavior tests for dynamic next-role selection."""

import unittest

from role_flow import next_role


def state(**overrides):
    value = {
        "schema_version": 1,
        "routing": "pending",
        "route": None,
        "evidence": "sufficient",
        "task_spec": "not_required",
        "implementation": "pending",
        "verification": "pending",
        "review": "not_required",
        "needs_adjudication": False,
        "context_isolation_benefit": False,
    }
    value.update(overrides)
    return value


class RoleFlowTest(unittest.TestCase):
    def test_selects_only_one_next_role_for_a_bounded_inline_task(self):
        self.assertEqual(
            {"status": "next", "role": "router", "mode": "serial", "reason": "routing_pending"},
            next_role(state()),
        )
        self.assertEqual(
            {"status": "next", "role": "implementer", "mode": "serial", "reason": "ready_to_implement"},
            next_role(state(routing="frozen", route="inline")),
        )
        self.assertEqual(
            {"status": "next", "role": "verifier", "mode": "tool", "reason": "implementation_complete"},
            next_role(state(routing="frozen", route="inline", implementation="complete")),
        )

    def test_planned_work_uses_only_the_missing_roles(self):
        self.assertEqual(
            {"status": "next", "role": "scout", "mode": "agent", "reason": "evidence_missing"},
            next_role(state(
                routing="frozen", route="planned", evidence="missing", task_spec="missing",
                context_isolation_benefit=True,
            )),
        )
        self.assertEqual(
            {"status": "next", "role": "specifier", "mode": "serial", "reason": "task_spec_missing"},
            next_role(state(routing="frozen", route="planned", task_spec="missing")),
        )

    def test_verification_failure_returns_to_router_unless_it_requires_adjudication(self):
        self.assertEqual(
            {"status": "next", "role": "router", "mode": "serial", "reason": "verification_failed"},
            next_role(state(routing="frozen", route="inline", implementation="complete", verification="failed")),
        )
        self.assertEqual(
            {"status": "next", "role": "adjudicator", "mode": "serial", "reason": "adjudication_required"},
            next_role(state(needs_adjudication=True)),
        )

    def test_review_is_optional_and_high_risk_review_is_independent(self):
        self.assertEqual(
            {"status": "done", "reason": "verification_complete"},
            next_role(state(
                routing="frozen", route="inline", implementation="complete", verification="passed",
            )),
        )
        self.assertEqual(
            {"status": "next", "role": "reviewer", "mode": "agent", "reason": "review_pending"},
            next_role(state(
                routing="frozen", route="planned", implementation="complete", verification="passed",
                review="pending",
            )),
        )

    def test_planned_flow_has_one_minimal_path_per_phase(self):
        states = [
            state(routing="frozen", route="planned", evidence="missing", task_spec="missing"),
            state(routing="frozen", route="planned", task_spec="missing"),
            state(routing="frozen", route="planned"),
            state(routing="frozen", route="planned", implementation="complete"),
            state(
                routing="frozen", route="planned", implementation="complete", verification="passed",
                review="pending",
            ),
            state(routing="frozen", route="planned", implementation="complete", verification="passed"),
        ]

        self.assertEqual(
            ["scout", "specifier", "implementer", "verifier", "reviewer", None],
            [next_role(item).get("role") for item in states],
        )

    def test_rejects_inconsistent_or_unknown_state(self):
        with self.assertRaisesRegex(ValueError, "route"):
            next_role(state(routing="frozen", route=None))
        with self.assertRaisesRegex(ValueError, "fields"):
            next_role(state(extra=True))

    def test_rejects_invalid_state_values_before_selecting_a_role(self):
        cases = (
            ({"schema_version": 2}, "schema_version"),
            ({"routing": "unknown"}, "routing"),
            ({"routing": "pending", "route": "inline"}, "before routing"),
            ({"evidence": "unknown"}, "evidence"),
            ({"task_spec": "unknown"}, "task_spec"),
            ({"implementation": "unknown"}, "implementation"),
            ({"verification": "unknown"}, "verification"),
            ({"review": "unknown"}, "review"),
            ({"needs_adjudication": "yes"}, "needs_adjudication"),
            ({"implementation": "pending", "verification": "passed"}, "requires completed"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, message):
                next_role(state(**overrides))


if __name__ == "__main__":
    unittest.main()
