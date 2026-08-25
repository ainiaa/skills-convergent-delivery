#!/usr/bin/env python3
"""Regression tests for frozen multi-model worker profiles."""

import unittest

from worker_profile import fingerprint, validate_worker_profile


def profile(**overrides):
    value = {
        "schema_version": 1,
        "worker_id": "research-1",
        "role": "research",
        "runner_id": "openai-compatible-v1",
        "requested": {"model": "deepseek-chat", "reasoning_effort": "high"},
        "effective": {"provider": "deepseek", "model": "deepseek-chat", "reasoning_effort": "high"},
        "permissions": {"workspace": "read", "shell": False, "network": "egress"},
        "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 12000},
    }
    value.update(overrides)
    identity = {key: item for key, item in value.items() if key != "profile_fingerprint"}
    return {**identity, "profile_fingerprint": fingerprint(identity)}


class WorkerProfileTest(unittest.TestCase):
    def test_accepts_frozen_requested_and_effective_model_contract(self):
        value = profile()
        self.assertEqual(value, validate_worker_profile(value))

    def test_rejects_unbounded_budget_or_worker_chosen_effective_values(self):
        unbounded = profile(budget={"max_turns": 0, "timeout_seconds": 120, "max_output_chars": 12000})
        with self.assertRaisesRegex(ValueError, "max_turns"):
            validate_worker_profile(unbounded)

        changed = profile()
        changed["effective"]["model"] = "another-model"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            validate_worker_profile(changed)

    def test_rejects_unsafe_external_or_reviewer_permissions(self):
        with self.assertRaisesRegex(ValueError, "reviewer"):
            validate_worker_profile(profile(role="reviewer", permissions={
                "workspace": "write", "shell": False, "network": "egress"
            }))
        with self.assertRaisesRegex(ValueError, "external"):
            validate_worker_profile(profile(permissions={
                "workspace": "read", "shell": True, "network": "egress"
            }))


if __name__ == "__main__":
    unittest.main()
