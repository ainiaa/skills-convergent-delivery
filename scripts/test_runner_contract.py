#!/usr/bin/env python3
"""Tests for the immutable, prompt-free runner launch contract."""

import unittest

from runner_contract import fingerprint as contract_fingerprint, freeze_launch, runner_results_complete, validate_launch
from worker_profile import fingerprint


def profile(**overrides):
    value = {
        "schema_version": 1,
        "worker_id": "research-1",
        "role": "research",
        "runner_id": "openai-compatible-v1",
        "requested": {"model": "glm-5.2", "reasoning_effort": "high"},
        "effective": {"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
        "permissions": {"workspace": "read", "shell": False, "network": "egress"},
        "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 12000},
    }
    value.update(overrides)
    identity = {key: item for key, item in value.items() if key != "profile_fingerprint"}
    return {**identity, "profile_fingerprint": fingerprint(identity)}


class RunnerContractTest(unittest.TestCase):
    def test_freezes_profile_configuration_and_prompt_fingerprint_without_storing_prompt(self):
        launch = freeze_launch(
            profile(), "Review this confidential change", {"api_key_env": "GLM_API_KEY"}
        )

        self.assertEqual("planned", launch["status"])
        self.assertEqual("openai-compatible-v1", launch["runner_id"])
        self.assertEqual("GLM_API_KEY", launch["configuration"]["api_key_env"])
        self.assertNotIn("Review this confidential change", str(launch))
        self.assertEqual(launch, validate_launch(launch, "Review this confidential change"))

    def test_rejects_altered_prompt_or_launch_contents(self):
        launch = freeze_launch(profile(), "Review", {"api_key_env": "GLM_API_KEY"})

        with self.assertRaisesRegex(ValueError, "prompt"):
            validate_launch(launch, "Different review")
        launch["configuration"]["api_key_env"] = "OTHER_KEY"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            validate_launch(launch, "Review")

    def test_requires_a_completed_result_for_each_frozen_launch(self):
        launch = freeze_launch(profile(), "Review", {"api_key_env": "GLM_API_KEY"})
        result = {
            "schema_version": 1, "runner_id": "openai-compatible-v1",
            "launch_fingerprint": launch["launch_fingerprint"], "status": "unknown",
            "error_type": "TimeoutError",
        }
        result["receipt_fingerprint"] = contract_fingerprint(result)

        self.assertFalse(runner_results_complete([launch], [result]))
        result = {**result, "status": "completed", "error_type": None}
        result.pop("error_type")
        result.update(response_id="request-1", response_model="glm-5.2", usage=None,
                      response_fingerprint="a" * 64)
        result["receipt_fingerprint"] = contract_fingerprint({
            key: item for key, item in result.items() if key != "receipt_fingerprint"
        })
        self.assertTrue(runner_results_complete([launch], [result]))

        result["response_model"] = "another-model"
        result["receipt_fingerprint"] = contract_fingerprint({
            key: item for key, item in result.items() if key != "receipt_fingerprint"
        })
        with self.assertRaisesRegex(ValueError, "model"):
            runner_results_complete([launch], [result])

    def test_rejects_malformed_completed_or_unknown_receipt_fields(self):
        launch = freeze_launch(profile(), "Review", {"api_key_env": "GLM_API_KEY"})
        completed = {
            "schema_version": 1, "runner_id": "openai-compatible-v1",
            "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
            "response_id": 1, "response_model": "glm-5.2", "usage": [],
            "response_fingerprint": "not-a-digest",
        }
        completed["receipt_fingerprint"] = contract_fingerprint(completed)
        with self.assertRaisesRegex(ValueError, "fields"):
            runner_results_complete([launch], [completed])

        unknown = {
            "schema_version": 1, "runner_id": "openai-compatible-v1",
            "launch_fingerprint": launch["launch_fingerprint"], "status": "unknown",
            "error_type": None,
        }
        unknown["receipt_fingerprint"] = contract_fingerprint(unknown)
        with self.assertRaisesRegex(ValueError, "fields"):
            runner_results_complete([launch], [unknown])


if __name__ == "__main__":
    unittest.main()
