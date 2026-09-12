#!/usr/bin/env python3
"""Tests for the host-neutral fixed-role dispatch plan."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from role_dispatch import plan_dispatch, plan_read_only_fanout
from worker_profile import fingerprint as profile_fingerprint


ROLE_DISPATCH = Path(__file__).with_name("role_dispatch.py")


def read_only_scout(**overrides):
    value = {
        "schema_version": 1, "worker_id": "scout-1", "role": "scout",
        "runner_id": "codex-exec-v1",
        "requested": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "effective": {"provider": "openai", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "permissions": {"workspace": "read", "shell": True, "network": "egress"},
        "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 12000},
    }
    value.update(overrides)
    identity = {key: item for key, item in value.items() if key != "profile_fingerprint"}
    return {**identity, "profile_fingerprint": profile_fingerprint(identity)}


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
    def test_dispatch_and_fanout_reject_invalid_or_unsafe_inputs(self):
        self.assertEqual(
            {"status": "done", "reason": "verification_complete"},
            plan_dispatch(self.profiles, state(
                routing="frozen", route="inline", implementation="complete", verification="passed"
            )),
        )
        with self.assertRaisesRegex(ValueError, "heterogeneity"):
            plan_read_only_fanout(
                self.profiles, [{"task_id": "scout", "role": "scout"}], require_heterogeneous="yes"
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            plan_read_only_fanout(self.profiles, [{"task_id": "same", "role": "scout"}] * 2)
        writable = {"roles": dict(self.profiles["roles"])}
        writable["roles"]["scout"] = {**writable["roles"]["implementer"], "role": "scout"}
        with self.assertRaises(ValueError):
            plan_read_only_fanout(writable, [{"task_id": "scout", "role": "scout"}])

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
        self.assertEqual("external_runner", result["executor"])
        self.assertNotIn("spawn", result)
        self.assertEqual(self.profiles["roles"]["scout"], result["profile"])
        self.assertEqual(self.profiles["roles"]["scout"]["profile_fingerprint"], result["profile_fingerprint"])

    def test_implementer_plan_uses_an_external_runner_instead_of_inheriting_the_controller_model(self):
        result = plan_dispatch(self.profiles, state(
            routing="frozen", route="delegated", context_isolation_benefit=True,
        ))
        self.assertEqual("implementer", result["role"])
        self.assertEqual("external_runner", result["executor"])
        self.assertNotIn("spawn", result)

    def test_claude_code_agent_plan_uses_the_same_external_runner_boundary(self):
        claude = resolve(
            None, workspace=Path(self.temporary.name) / "repo", home=Path(self.temporary.name) / "home",
            profile_name="claude-code",
        )
        result = plan_dispatch(claude, state(
            routing="frozen", route="planned", evidence="missing",
            context_isolation_benefit=True,
        ))
        self.assertEqual("external_runner", result["executor"])
        self.assertEqual("claude-code-v1", result["runner_id"])
        self.assertNotIn("spawn", result)
        self.assertEqual(claude["roles"]["scout"], result["profile"])

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

    def test_fanout_rejects_missing_and_writable_profiles(self):
        with self.assertRaisesRegex(ValueError, "profile is missing"):
            plan_read_only_fanout(
                {"roles": {}}, [{"task_id": "scout", "role": "scout"}],
            )
        with self.assertRaisesRegex(ValueError, "rejects writable profiles"):
            plan_read_only_fanout(
                {"roles": {"scout": read_only_scout()}},
                [{"task_id": "scout", "role": "scout"}],
            )

    def test_fanout_enforces_task_bounds_and_distinct_heterogeneous_profiles(self):
        with self.assertRaisesRegex(ValueError, "at most three tasks"):
            plan_read_only_fanout(self.profiles, [])
        identical = {
            "roles": {
                "scout": read_only_scout(permissions={
                    "workspace": "read", "shell": False, "network": "egress",
                }),
                "reviewer": read_only_scout(
                    worker_id="reviewer-1", role="reviewer",
                    permissions={"workspace": "read", "shell": False, "network": "egress"},
                ),
            },
        }
        with self.assertRaisesRegex(ValueError, "heterogeneous fan-out requires distinct"):
            plan_read_only_fanout(
                identical,
                [{"task_id": "a", "role": "scout"}, {"task_id": "b", "role": "reviewer"}],
                require_heterogeneous=True,
            )

    def test_cli_reports_fanout_errors_as_structured_failures(self):
        tasks = Path(self.temporary.name) / "invalid-fanout.json"
        tasks.write_text(json.dumps([{"task_id": "", "role": "scout"}]), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(ROLE_DISPATCH), "--workspace", self.temporary.name,
             "--fanout", str(tasks)],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("error", json.loads(result.stdout)["status"])

    def test_cli_exposes_the_explicit_read_only_fanout_plan(self):
        tasks = Path(self.temporary.name) / "fanout.json"
        tasks.write_text(json.dumps([
            {"task_id": "b", "role": "reviewer"}, {"task_id": "a", "role": "scout"},
        ]), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(ROLE_DISPATCH), "--workspace", self.temporary.name, "--fanout", str(tasks)],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual("external_runner_fanout", plan["executor"])
        self.assertEqual(["a", "b"], [item["task_id"] for item in plan["tasks"]])

    def test_cli_requires_an_explicit_distinct_profile_for_heterogeneous_fanout(self):
        tasks = Path(self.temporary.name) / "heterogeneous-fanout.json"
        tasks.write_text(json.dumps([
            {"task_id": "scout", "role": "scout"}, {"task_id": "review", "role": "reviewer"},
        ]), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, str(ROLE_DISPATCH), "--workspace", self.temporary.name,
                "--fanout", str(tasks), "--require-heterogeneous",
                "--role", "reviewer=glm-5.2@high",
            ], text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["heterogeneous"])


if __name__ == "__main__":
    unittest.main()
