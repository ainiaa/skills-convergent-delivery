#!/usr/bin/env python3
"""Tests for the intentionally small runner capability registry."""

import unittest

from runner_registry import capabilities, validate_runner_profile
from worker_profile import fingerprint


def profile(runner_id="codex-exec-v1", **overrides):
    value = {
        "schema_version": 1,
        "worker_id": "implementer-1",
        "role": "implementer",
        "runner_id": runner_id,
        "requested": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "effective": {"provider": "openai", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "permissions": {"workspace": "write", "shell": True, "network": "egress"},
        "budget": {"max_turns": 2, "timeout_seconds": 180, "max_output_chars": 12000},
    }
    value.update(overrides)
    identity = {key: item for key, item in value.items() if key != "profile_fingerprint"}
    return {**identity, "profile_fingerprint": fingerprint(identity)}


class RunnerRegistryTest(unittest.TestCase):
    def test_exposes_explicit_capability_sets(self):
        self.assertEqual("local_process", capabilities("codex-exec-v1")["kind"])
        self.assertEqual("network_request", capabilities("openai-compatible-v1")["kind"])
        self.assertEqual("local_process", capabilities("claude-code-v1")["kind"])
        self.assertEqual(["egress"], capabilities("openai-compatible-v1")["network"])
        with self.assertRaisesRegex(ValueError, "unknown"):
            capabilities("future-runner")
        self.assertNotIn("openai-compatible", capabilities("openai-compatible-v1")["providers"])

    def test_validates_runner_specific_permissions_and_model_identity(self):
        self.assertEqual(profile(), validate_runner_profile(profile()))
        external = profile(
            "openai-compatible-v1", role="scout",
            requested={"model": "glm-5.2", "reasoning_effort": "high"},
            effective={"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
            permissions={"workspace": "read", "shell": False, "network": "egress"},
        )
        self.assertEqual(external, validate_runner_profile(external))

        claude = profile(
            "claude-code-v1",
            requested={"model": "sonnet", "reasoning_effort": "high"},
            effective={"provider": "anthropic", "model": "sonnet", "reasoning_effort": "high"},
            permissions={"workspace": "read", "shell": False, "network": "egress"},
        )
        self.assertEqual(claude, validate_runner_profile(claude))

        no_egress = profile(
            "openai-compatible-v1", role="scout",
            requested={"model": "glm-5.2", "reasoning_effort": "high"},
            effective={"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
            permissions={"workspace": "read", "shell": False, "network": "none"},
        )
        with self.assertRaisesRegex(ValueError, "network"):
            validate_runner_profile(no_egress)

        self.assertEqual(
            profile(permissions={"workspace": "read", "shell": False, "network": "egress"}),
            validate_runner_profile(profile(permissions={"workspace": "read", "shell": False, "network": "egress"})),
        )

        wrong = profile(effective={"provider": "deepseek", "model": "deepseek-chat", "reasoning_effort": "high"})
        with self.assertRaisesRegex(ValueError, "codex"):
            validate_runner_profile(wrong)

    def test_rejects_roles_outside_each_runner_boundary(self):
        with self.assertRaisesRegex(ValueError, "role"):
            validate_runner_profile(profile(role="verifier", permissions={
                "workspace": "read", "shell": True, "network": "egress"
            }))
        with self.assertRaisesRegex(ValueError, "role"):
            validate_runner_profile(profile("openai-compatible-v1", role="adjudicator", permissions={
                "workspace": "read", "shell": False, "network": "egress"
            }))


if __name__ == "__main__":
    unittest.main()
