#!/usr/bin/env python3
"""Tests for read-only OpenAI-compatible request planning; no network call is made."""

import unittest

from openai_compatible_runner import execute_request, plan_request
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


class OpenAICompatibleRunnerTest(unittest.TestCase):
    def test_plans_a_bounded_read_only_request_without_storing_a_secret_or_prompt(self):
        receipt = plan_request(
            profile(), "Review the code", base_url="https://api.example.test/v1",
            api_key_env="GLM_API_KEY", effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        self.assertEqual("https://api.example.test/v1/chat/completions", receipt["url"])
        self.assertEqual("glm-5.2", receipt["body"]["model"])
        self.assertEqual({"field": "thinking.type", "value": "enabled"}, receipt["body"]["effort"])
        self.assertNotIn("Review the code", str(receipt))
        self.assertNotIn("GLM_API_KEY", str(receipt))
        self.assertEqual("runner", receipt["evidence_source"])

    def test_rejects_write_or_shell_capability(self):
        unsafe = profile(permissions={"workspace": "read", "shell": True, "network": "egress"})
        with self.assertRaisesRegex(ValueError, "external"):
            plan_request(unsafe, "Review", base_url="https://api.example.test/v1", api_key_env="KEY",
                         effort_binding={"field": "thinking.type", "value": "enabled"})

    def test_requires_an_explicit_provider_effort_mapping(self):
        with self.assertRaisesRegex(ValueError, "effort binding"):
            plan_request(profile(), "Review", base_url="https://api.example.test/v1", api_key_env="KEY")

    def test_executes_only_with_explicit_egress_and_binds_the_returned_model(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b'{"id":"request-1","model":"glm-5.2","usage":{"total_tokens":12}}'

        receipt = execute_request(
            profile(), "Review", base_url="https://api.example.test/v1", api_key="test-key",
            allow_network=True, opener=lambda request, timeout: Response(),
            effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("request-1", receipt["response_id"])
        self.assertEqual("glm-5.2", receipt["response_model"])

    def test_rejects_a_response_that_exceeds_the_frozen_output_budget(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b"{}"

        small = profile(budget={"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 1})
        with self.assertRaisesRegex(ValueError, "output budget"):
            execute_request(
                small, "Review", base_url="https://api.example.test/v1", api_key="test-key",
                allow_network=True, opener=lambda request, timeout: Response(),
                effort_binding={"field": "thinking.type", "value": "enabled"},
            )


if __name__ == "__main__":
    unittest.main()
