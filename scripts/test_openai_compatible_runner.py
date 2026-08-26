#!/usr/bin/env python3
"""Tests for read-only OpenAI-compatible request planning; no network call is made."""

import io
import unittest
from unittest.mock import patch

from openai_compatible_runner import execute_request, plan_request
from runner_contract import freeze_launch
from worker_profile import fingerprint


def profile(**overrides):
    value = {
        "schema_version": 1,
        "worker_id": "research-1",
        "role": "scout",
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
            profile(), "Review the code", base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key_env="GLM_API_KEY", effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        self.assertEqual("https://open.bigmodel.cn/api/paas/v4/chat/completions", receipt["configuration"]["url"])
        self.assertEqual({"field": "thinking.type", "value": "enabled"}, receipt["configuration"]["effort_binding"])
        self.assertNotIn("Review the code", str(receipt))
        self.assertEqual("GLM_API_KEY", receipt["configuration"]["api_key_env"])
        self.assertEqual("runner", receipt["evidence_source"])

    def test_rejects_write_or_shell_capability(self):
        unsafe = profile(permissions={"workspace": "read", "shell": True, "network": "egress"})
        with self.assertRaisesRegex(ValueError, "shell"):
            plan_request(unsafe, "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="KEY",
                         effort_binding={"field": "thinking.type", "value": "enabled"})

    def test_requires_an_explicit_provider_effort_mapping(self):
        with self.assertRaisesRegex(ValueError, "effort binding"):
            plan_request(profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="KEY")

    def test_rejects_credentials_or_effort_bindings_not_registered_for_the_provider(self):
        with self.assertRaisesRegex(ValueError, "credential"):
            plan_request(
                profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4",
                api_key_env="AWS_SECRET_ACCESS_KEY",
                effort_binding={"field": "thinking.type", "value": "enabled"},
            )
        with self.assertRaisesRegex(ValueError, "effort"):
            plan_request(
                profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4",
                api_key_env="GLM_API_KEY", effort_binding={"field": "reasoning.effort", "value": "high"},
            )

    def test_executes_only_with_explicit_egress_and_binds_the_returned_model(self):
        class Response:
            def __init__(self):
                self.body = io.BytesIO(
                    b'{"id":"request-1","model":"glm-5.2","usage":{"total_tokens":12}}'
                )

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _size=-1):
                return self.body.read(_size)

        launch = plan_request(
            profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="GLM_API_KEY",
            effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
            receipt = execute_request(
                launch, "Review", allow_network=True, opener=lambda request, timeout: Response(),
            )
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("request-1", receipt["response_id"])
        self.assertEqual("glm-5.2", receipt["response_model"])

    def test_can_return_content_to_the_immediate_caller_without_putting_it_in_the_receipt(self):
        class Response:
            def __init__(self):
                self.body = io.BytesIO(
                    b'{"id":"request-1","model":"glm-5.2",'
                    b'"choices":[{"message":{"content":"[]"}}]}'
                )

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _size=-1):
                return self.body.read(_size)

        launch = plan_request(
            profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="GLM_API_KEY",
            effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
            receipt, content = execute_request(
                launch, "Review", allow_network=True, capture_content=True,
                opener=lambda request, timeout: Response(),
            )
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("[]", content)
        self.assertNotIn("[]", receipt)

    def test_rejects_a_response_that_exceeds_the_frozen_output_budget(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _size=-1):
                return b"{}"

        small = profile(budget={"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 1})
        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
            receipt = execute_request(
                plan_request(small, "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="GLM_API_KEY",
                             effort_binding={"field": "thinking.type", "value": "enabled"}),
                "Review", allow_network=True, opener=lambda request, timeout: Response(),
            )
        self.assertEqual("unknown", receipt["status"])

    def test_rejects_an_empty_response_id_before_issuing_a_completed_receipt(self):
        class Response:
            def __init__(self):
                self.body = io.BytesIO(b'{"id":"","model":"glm-5.2"}')

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, size=-1):
                return self.body.read(size)

        launch = plan_request(
            profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="GLM_API_KEY",
            effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
            receipt = execute_request(
                launch, "Review", allow_network=True, opener=lambda request, timeout: Response(),
            )

        self.assertEqual("unknown", receipt["status"])

    def test_returns_a_terminal_receipt_when_the_frozen_credential_is_missing(self):
        launch = plan_request(
            profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="GLM_API_KEY",
            effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        with patch.dict("os.environ", {}, clear=True):
            receipt = execute_request(launch, "Review", allow_network=True)

        self.assertEqual("unknown", receipt["status"])
        self.assertEqual("missing_credential", receipt["error_type"])

    def test_rejects_an_unapproved_or_ambiguous_credential_origin(self):
        with self.assertRaisesRegex(ValueError, "approved"):
            plan_request(profile(), "Review", base_url="https://127.0.0.1/v1", api_key_env="KEY",
                         effort_binding={"field": "thinking.type", "value": "enabled"})
        with self.assertRaisesRegex(ValueError, "base URL"):
            plan_request(profile(), "Review", base_url="https://open.bigmodel.cn/v1?target=elsewhere", api_key_env="KEY",
                         effort_binding={"field": "thinking.type", "value": "enabled"})

    def test_execution_revalidates_the_frozen_endpoint_before_sending_credentials(self):
        launch = freeze_launch(profile(), "Review", {
            "url": "https://attacker.example.test/chat/completions",
            "api_key_env": "GLM_API_KEY",
            "effort_binding": {"field": "thinking.type", "value": "enabled"},
        })

        with self.assertRaisesRegex(ValueError, "approved"):
            execute_request(launch, "Review", allow_network=True)


if __name__ == "__main__":
    unittest.main()
