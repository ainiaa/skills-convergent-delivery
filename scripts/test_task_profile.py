#!/usr/bin/env python3
"""Behavior tests for deterministic task routing."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from task_profile import classify, freeze_routing, infer_path_risks, requires_full_closure


def profile(**overrides):
    value = {
        "schema_version": 2,
        "assessment_phase": "frozen",
        "scope": "local",
        "coupling": "single",
        "uncertainty": "low",
        "verification": "local",
        "risk_flags": [],
        "cross_session": False,
        "delegable_tasks": 0,
        "context_isolation_benefit": False,
    }
    value.update(overrides)
    return value


class TaskProfileTest(unittest.TestCase):
    def test_local_known_task_stays_inline(self):
        self.assertEqual(classify(profile())["route"], "inline")

    def test_universal_completion_claim_forces_a_plan_and_is_exposed_to_the_controller(self):
        result = classify(profile(), "请深度审查并修复全部已知问题，不留遗漏")

        self.assertTrue(result["full_closure_required"])
        self.assertEqual("planned", result["route"])
        self.assertIn("full_closure_claim", result["reasons"])
        self.assertTrue(requires_full_closure("Are there any other bugs? Fix all of them."))

    def test_cli_accepts_the_raw_request_only_from_a_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.txt"
            request_path.write_text("彻底检查所有问题", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("task_profile.py")),
                 "--request-file", str(request_path)],
                input=json.dumps(profile()), text=True, capture_output=True, check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("planned", json.loads(result.stdout)["route"])

    def test_unknown_or_cross_service_task_requires_plan(self):
        self.assertEqual(classify(profile(uncertainty="high"))["route"], "planned")
        self.assertEqual(classify(profile(scope="cross-service"))["route"], "planned")

    def test_risk_changes_review_tier_not_execution_topology(self):
        result = classify(profile(risk_flags=["money"]))
        self.assertEqual(result["route"], "inline")
        self.assertEqual(result["review_tier"], "high")

    def test_delegation_requires_explicit_context_benefit(self):
        signals = profile(scope="cross-service", delegable_tasks=2)
        self.assertEqual(classify(signals)["route"], "planned")
        signals["context_isolation_benefit"] = True
        self.assertEqual(classify(signals)["route"], "delegated")

    def test_cross_session_always_uses_batch(self):
        self.assertEqual(classify(profile(cross_session=True))["route"], "batch")

    def test_provisional_profile_never_dispatches(self):
        result = classify(profile(assessment_phase="provisional", cross_session=True))
        self.assertEqual("planned", result["route"])
        self.assertEqual("batch", result["recommended_route"])

    def test_dependent_work_is_not_delegated(self):
        result = classify(profile(
            coupling="dependent", delegable_tasks=2, context_isolation_benefit=True,
        ))
        self.assertEqual("planned", result["route"])

    def test_complete_risk_enum_drives_high_review(self):
        for risk in ("time", "timezone", "sql", "mapper", "sensitive-log", "release-contract"):
            with self.subTest(risk=risk):
                self.assertEqual("high", classify(profile(risk_flags=[risk]))["review_tier"])

    def test_rejects_unknown_fields_unknown_risks_and_non_boolean_flags(self):
        invalid = (
            (profile(extra=True), "fields"),
            (profile(risk_flags=["typo-risk"]), "risk_flags"),
            (profile(cross_session="yes"), "cross_session"),
            (profile(context_isolation_benefit=1), "context_isolation_benefit"),
        )
        for value, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                classify(value)

    def test_cli_errors_are_structured_without_a_traceback(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("task_profile.py")), "--input", "file.json"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr)
        self.assertEqual("error", json.loads(result.stdout)["status"])

    def test_frozen_routing_binds_profile_route_review_and_scope(self):
        value = profile(scope="cross-service", risk_flags=["cross-service"])

        routing = freeze_routing(value, ["service-a", "service-b"])

        self.assertEqual(3, routing["schema_version"])
        self.assertEqual("planned", routing["route"])
        self.assertEqual("high", routing["review_tier"])
        self.assertTrue(routing["integration_required"])
        self.assertEqual(value, routing["profile"])
        self.assertEqual(64, len(routing["profile_fingerprint"]))

    def test_frozen_routing_binds_the_raw_request_closure_decision(self):
        routing = freeze_routing(profile(), ["."], request_text="彻底检查所有问题")

        self.assertTrue(routing["full_closure_required"])
        self.assertEqual("planned", routing["route"])
        self.assertEqual(64, len(routing["request_fingerprint"]))

    def test_scope_paths_are_canonical_and_risk_inference_is_conservative(self):
        with self.assertRaisesRegex(ValueError, "allowed_paths"):
            freeze_routing(profile(), ["../outside"])

        self.assertEqual(
            {"sql", "permission", "security"},
            infer_path_risks(["db/permission.sql"]),
        )


if __name__ == "__main__":
    unittest.main()
