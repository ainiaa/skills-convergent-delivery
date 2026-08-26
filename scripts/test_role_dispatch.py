#!/usr/bin/env python3
"""Tests for the host-neutral fixed-role dispatch plan."""

import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from role_dispatch import plan_dispatch


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


class RoleDispatchTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.profiles = resolve(None, workspace=root / "repo", home=root / "home")

    def tearDown(self):
        self.temporary.cleanup()

    def test_codex_agent_plan_explicitly_overrides_the_parent_model(self):
        result = plan_dispatch(self.profiles, state(
            routing="frozen", route="planned", evidence="missing",
            context_isolation_benefit=True,
        ))
        self.assertEqual("scout", result["role"])
        self.assertEqual("codex_subagent", result["executor"])
        self.assertEqual("gpt-5.6-terra", result["spawn"]["model"])
        self.assertEqual("medium", result["spawn"]["reasoning_effort"])
        self.assertEqual("none", result["spawn"]["fork_turns"])
        self.assertEqual(self.profiles["roles"]["scout"]["profile_fingerprint"], result["profile_fingerprint"])

    def test_implementer_plan_uses_luna_instead_of_inheriting_the_controller_model(self):
        result = plan_dispatch(self.profiles, state(
            routing="frozen", route="delegated", context_isolation_benefit=True,
        ))
        self.assertEqual("implementer", result["role"])
        self.assertEqual("gpt-5.6-luna", result["spawn"]["model"])
        self.assertEqual("high", result["spawn"]["reasoning_effort"])

    def test_serial_and_tool_roles_do_not_create_a_model_bound_subagent(self):
        serial = plan_dispatch(self.profiles, state(routing="frozen", route="inline"))
        tool = plan_dispatch(self.profiles, state(
            routing="frozen", route="inline", implementation="complete",
        ))
        self.assertEqual("controller", serial["executor"])
        self.assertNotIn("spawn", serial)
        self.assertEqual("tools", tool["executor"])
        self.assertNotIn("profile_fingerprint", tool)

    def test_invalid_or_missing_agent_profile_is_rejected(self):
        profiles = {"roles": {}}
        with self.assertRaisesRegex(ValueError, "profile"):
            plan_dispatch(profiles, state(
                routing="frozen", route="planned", evidence="missing",
                context_isolation_benefit=True,
            ))


if __name__ == "__main__":
    unittest.main()
