#!/usr/bin/env python3
"""Tests for read-only OpenAI-compatible request planning; no network call is made."""

import io
import unittest
from unittest.mock import patch

from openai_compatible_runner import _http_status_error, execute_request, plan_request
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
        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual(
            {"model": {"status": "observed", "observed": "glm-5.2"},
             "usage": {"status": "observed", "value": {"total_tokens": 12}}},
            receipt["attestation"],
        )

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

    def test_classifies_non_2xx_responses_as_http_errors_instead_of_parse_failures(self):
        class Response:
            status = 0
            url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

            def __init__(self, status, body):
                self.status = status
                self.body = io.BytesIO(body)

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
        for status in (400, 500):
            with self.subTest(status=status), patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
                receipt = execute_request(
                    launch, "Review", allow_network=True,
                    opener=lambda _request, status=status, **_kwargs: Response(status, b"<html>gateway</html>"),
                )
            self.assertEqual("unknown", receipt["status"])
            self.assertEqual(f"HTTPError:{status}", receipt["error_type"])

    def test_http_errors_carry_the_status_and_a_truncated_body_summary(self):
        class Response:
            status = 429
            url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

            def __init__(self, body):
                self.body = io.BytesIO(body)

            def read(self, size=-1):
                return self.body.read(size)

        error = _http_status_error(Response(b"x" * 500), 12000)
        self.addCleanup(error.close)

        self.assertEqual(429, error.code)
        self.assertEqual(200, len(error.msg))
        self.assertIn("429", str(error))

    def test_http_error_summary_respects_a_tiny_output_budget(self):
        class Response:
            status = 500
            url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

            def __init__(self, body):
                self.body = io.BytesIO(body)

            def read(self, size=-1):
                return self.body.read(size)

        error = _http_status_error(Response(b"x" * 500), 10)
        self.addCleanup(error.close)

        self.assertEqual(500, error.code)
        self.assertEqual(10, len(error.msg))

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

    def test_request_boundaries_reject_invalid_transport_configuration_and_payloads(self):
        from openai_compatible_runner import (
            _approved_url, _http_status_error, _open_without_redirect, _response_bytes, _response_content,
            _NoRedirect,
            _validate_approved_endpoint, _validate_provider_configuration, validate_effort_binding,
        )

        with self.assertRaisesRegex(ValueError, "binding is invalid"):
            validate_effort_binding({"field": "bad-field", "value": "enabled"})
        with self.assertRaisesRegex(ValueError, "environment name"):
            plan_request(profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="",
                         effort_binding={"field": "thinking.type", "value": "enabled"})
        self.assertIsNone(_NoRedirect().redirect_request())
        with patch("openai_compatible_runner.urllib.request.build_opener") as build_opener:
            _open_without_redirect("request", 1)
        build_opener.return_value.open.assert_called_once_with("request", timeout=1)
        with self.assertRaisesRegex(ValueError, "base URL"):
            _approved_url(profile(), 1)
        with self.assertRaisesRegex(ValueError, "endpoint"):
            _validate_approved_endpoint(profile(), "https://open.bigmodel.cn/not-completions")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            _validate_provider_configuration(
                profile(effective={"provider": "unknown", "model": "m", "reasoning_effort": "high"}),
                "GLM_API_KEY", {"field": "thinking.type", "value": "enabled"},
            )

        class BadResponse:
            def read(self, _size=-1):
                return "not bytes"

        with self.assertRaisesRegex(ValueError, "not bytes"):
            _response_bytes(BadResponse(), 10)
        with self.assertRaisesRegex(ValueError, "no choices"):
            _response_content({})
        with self.assertRaisesRegex(ValueError, "content"):
            _response_content({"choices": [{"message": {"content": " "}}]})

        class BrokenResponse:
            status = 502
            url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

            def read(self, _size=-1):
                raise OSError("unavailable")

        error = _http_status_error(BrokenResponse(), 10)
        self.addCleanup(error.close)
        self.assertEqual("", error.msg)

        launch = plan_request(
            profile(), "Review", base_url="https://open.bigmodel.cn/api/paas/v4", api_key_env="GLM_API_KEY",
            effort_binding={"field": "thinking.type", "value": "enabled"},
        )
        with self.assertRaisesRegex(ValueError, "explicit allow_network"):
            execute_request(launch, "Review")
        with patch("openai_compatible_runner.validate_launch", return_value={"runner_id": "other"}):
            with self.assertRaisesRegex(ValueError, "does not select"):
                execute_request(launch, "Review", allow_network=True)
        malformed = freeze_launch(profile(), "Review", {})
        with self.assertRaisesRegex(ValueError, "configuration"):
            execute_request(malformed, "Review", allow_network=True)

        class Response:
            def __init__(self):
                self.body = io.BytesIO(b'{"id":"request-1","model":"glm-5.2","usage":1}')

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, size=-1):
                return self.body.read(size)

        with patch.dict("os.environ", {"GLM_API_KEY": "test-key"}):
            receipt = execute_request(launch, "Review", allow_network=True, opener=lambda *_args, **_kwargs: Response())
        self.assertEqual("unknown", receipt["status"])


if __name__ == "__main__":
    unittest.main()
