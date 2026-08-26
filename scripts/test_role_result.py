#!/usr/bin/env python3
"""Tests for the bounded, structured output from read-only model roles."""

import json
import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from role_result import prompt_for_role, result_from_output, validate_role_result
from runner_contract import freeze_launch


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
            "findings": [{"summary": "The focused test is missing.", "evidence": ["scripts/test_role_result.py"]}],
            "next_action": "clarify",
        })

        result = result_from_output(launch, {"status": "available", "content": output})

        self.assertEqual("available", result["status"])
        self.assertEqual(launch["launch_fingerprint"], result["launch_fingerprint"])
        self.assertEqual("scout", result["role"])
        self.assertNotIn("content", result)
        self.assertNotIn(output, json.dumps(result))
        self.assertEqual(result, validate_role_result(result, launch))

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
        self.assertIn("Return only JSON", prompt)


if __name__ == "__main__":
    unittest.main()
