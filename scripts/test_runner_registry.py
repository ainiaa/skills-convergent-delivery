#!/usr/bin/env python3
"""Tests for the intentionally small runner capability registry."""

import unittest

from runner_registry import capabilities, validate_runner_profile
from worker_profile import fingerprint


def profile(runner_id="codex-exec-v1", **overrides):
    value = {
        "schema_version": 1,
        "worker_id": "implementation-1",
        "role": "implementation",
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
    def test_exposes_two_explicit_capability_sets(self):
        self.assertEqual("local_process", capabilities("codex-exec-v1")["kind"])
        self.assertEqual("network_request", capabilities("openai-compatible-v1")["kind"])
        with self.assertRaisesRegex(ValueError, "unknown"):
            capabilities("future-runner")

    def test_validates_runner_specific_permissions_and_model_identity(self):
        self.assertEqual(profile(), validate_runner_profile(profile()))
        external = profile(
            "openai-compatible-v1", role="research",
            requested={"model": "glm-5.2", "reasoning_effort": "high"},
            effective={"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
            permissions={"workspace": "read", "shell": False, "network": "egress"},
        )
        self.assertEqual(external, validate_runner_profile(external))

        wrong = profile(effective={"provider": "deepseek", "model": "deepseek-chat", "reasoning_effort": "high"})
        with self.assertRaisesRegex(ValueError, "codex"):
            validate_runner_profile(wrong)


if __name__ == "__main__":
    unittest.main()
