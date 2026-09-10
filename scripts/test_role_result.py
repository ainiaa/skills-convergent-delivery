#!/usr/bin/env python3
"""Tests for the bounded, structured output from read-only model roles."""

import json
import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from role_result import (
    prompt_for_review, prompt_for_role, result_from_output, validate_evidence_reference,
    review_result, validate_available_result, validate_role_result,
)
from runner_contract import fingerprint, freeze_launch


class RoleResultTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        workspace = Path(self.temporary.name)
        self.profiles = resolve(None, workspace=workspace, home=workspace / "home")

    def tearDown(self):
        self.temporary.cleanup()

    def launch(self, role="scout"):
        return freeze_launch(self.profiles["roles"][role], "collect evidence", {})

    def test_valid_json_output_becomes_a_fingerprinted_result_without_raw_content(self):
        launch = self.launch()
        output = json.dumps({
            "findings": [{"summary": "The focused test is missing.", "evidence": [{
                "kind": "file", "reference": "scripts/test_role_result.py:26",
                "content_fingerprint": "a" * 64,
            }]}],
            "next_action": "clarify",
        })

        result = result_from_output(launch, {"status": "available", "content": output})

        self.assertEqual("available", result["status"])
        self.assertEqual(launch["launch_fingerprint"], result["launch_fingerprint"])
        self.assertEqual("scout", result["role"])
        self.assertNotIn('"content":', json.dumps(result))
        self.assertNotIn(output, json.dumps(result))
        self.assertEqual(result, validate_role_result(result, launch))

    def test_typed_evidence_references_require_a_content_fingerprint(self):
        launch = self.launch()
        output = json.dumps({
            "findings": [{
                "summary": "The focused test is missing.",
                "evidence": [{
                    "kind": "file", "reference": "scripts/test_role_result.py:26",
                    "content_fingerprint": "a" * 64,
                }],
            }],
            "next_action": "clarify",
        })

        result = result_from_output(launch, {"status": "available", "content": output})

        self.assertEqual(2, result["schema_version"])
        self.assertEqual("file", result["findings"][0]["evidence"][0]["kind"])
        self.assertEqual(result, validate_role_result(result, launch))

        malformed = result_from_output(launch, {"status": "available", "content": json.dumps({
            "findings": [{"summary": "missing fingerprint", "evidence": [{
                "kind": "file", "reference": "scripts/test_role_result.py:26",
            }]}],
            "next_action": "clarify",
        })})
        self.assertEqual(("invalid", "invalid_contract"), (malformed["status"], malformed["reason"]))

        unsafe_file = result_from_output(launch, {"status": "available", "content": json.dumps({
            "findings": [{"summary": "absolute file", "evidence": [{
                "kind": "file", "reference": "/tmp/result.py:1", "content_fingerprint": "a" * 64,
            }]}],
            "next_action": "clarify",
        })})
        self.assertEqual(("invalid", "invalid_contract"), (unsafe_file["status"], unsafe_file["reason"]))

    def test_validates_the_prior_v1_result_for_existing_ledgers(self):
        launch = self.launch()
        legacy = {
            "schema_version": 1,
            "launch_fingerprint": launch["launch_fingerprint"],
            "role": "scout",
            "status": "available",
            "findings": [{"summary": "legacy", "evidence": ["scripts/test_role_result.py"]}],
            "next_action": "verify",
        }
        legacy["result_fingerprint"] = fingerprint(legacy)

        self.assertEqual(legacy, validate_role_result(legacy, launch))

    def test_empty_and_invalid_outputs_are_explicit_without_retaining_the_model_text(self):
        launch = self.launch("reviewer")

        unavailable = result_from_output(launch, {"status": "unavailable"})
        invalid = result_from_output(launch, {"status": "available", "content": "not json"})

        self.assertEqual({"status": "unavailable", "reason": "output_unavailable"}, {
            key: unavailable[key] for key in ("status", "reason")
        })
        self.assertEqual({"status": "invalid", "reason": "invalid_json"}, {
            key: invalid[key] for key in ("status", "reason")
        })
        self.assertNotIn("not json", json.dumps(invalid))
        self.assertEqual(invalid, validate_role_result(invalid, launch))

    def test_invalid_contract_and_non_read_only_role_never_produce_a_usable_result(self):
        launch = self.launch()
        malformed = result_from_output(launch, {"status": "available", "content": "{}"})
        implementer = result_from_output(self.launch("implementer"), {
            "status": "available", "content": "{}",
        })

        self.assertEqual(("invalid", "invalid_contract"), (malformed["status"], malformed["reason"]))
        self.assertEqual(("unavailable", "role_not_supported"), (
            implementer["status"], implementer["reason"]
        ))

    def test_prompt_for_role_preserves_the_task_and_requires_only_the_result_schema(self):
        prompt = prompt_for_role("scout", "Inspect the changed files.")

        self.assertTrue(prompt.startswith("Inspect the changed files."))
        self.assertIn('"findings"', prompt)
        self.assertIn('"next_action"', prompt)
        self.assertIn('"content_fingerprint"', prompt)
        self.assertIn("Return only JSON", prompt)

    def test_evidence_contract_accepts_safe_kinds_and_rejects_unsafe_locations(self):
        fingerprint_value = "a" * 64
        for kind, reference in (
            ("command", "bash scripts/check.sh"),
            ("url", "https://example.com/evidence"),
            ("artifact", "artifacts/report.json"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(kind, validate_evidence_reference({
                    "kind": kind, "reference": reference, "content_fingerprint": fingerprint_value,
                })["kind"])
        for kind, reference in (("url", "http://example.com"), ("artifact", "../secret")):
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, "evidence|URL|artifact"):
                validate_evidence_reference({
                    "kind": kind, "reference": reference, "content_fingerprint": fingerprint_value,
                })

    def test_review_prompt_hides_the_original_prompt_for_a_blind_request(self):
        blind = prompt_for_review("private prompt", {"mode": "blind", "axis": "quality"})
        shared = prompt_for_review("shared prompt", {"mode": "shared", "axis": "quality"})
        self.assertNotIn("private prompt", blind)
        self.assertIn("shared prompt", shared)
        with self.assertRaisesRegex(ValueError, "prompt"):
            prompt_for_review("", {})

    def test_result_contract_rejects_bad_findings_and_only_reviewers_bind_review_records(self):
        launch = self.launch()
        for content in (
            json.dumps({"findings": [], "next_action": "unknown"}),
            json.dumps({"findings": [{"summary": "x", "evidence": []}], "next_action": "verify"}),
        ):
            with self.subTest(content=content):
                result = result_from_output(launch, {"status": "available", "content": content})
                self.assertEqual("invalid", result["status"])
        available = result_from_output(launch, {"status": "available", "content": json.dumps({
            "findings": [{"summary": "x", "evidence": [{
                "kind": "file", "reference": "scripts/test_role_result.py:1", "content_fingerprint": "a" * 64,
            }]}], "next_action": "verify",
        })})
        available["result_fingerprint"] = "bad"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            validate_available_result(available)
        with self.assertRaisesRegex(ValueError, "reviewer"):
            review_result(launch, {"status": "pass"})
        reviewer = self.launch("reviewer")
        result = review_result(reviewer, {"status": "pass"})
        self.assertEqual(result, validate_role_result(result, reviewer))


if __name__ == "__main__":
    unittest.main()
