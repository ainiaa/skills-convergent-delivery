#!/usr/bin/env python3
"""Behavior tests for deterministic task routing."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from task_profile import classify, freeze_routing, infer_path_risks, validate_frozen_routing


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
    def test_routing_contract_rejects_each_invalid_profile_and_frozen_identity_field(self):
        cases = (
            profile(schema_version=1), profile(assessment_phase="unknown"), profile(scope="unknown"),
            profile(coupling="unknown"), profile(uncertainty="unknown"), profile(verification="unknown"),
            profile(risk_flags="money"), profile(delegable_tasks=True),
        )
        for invalid in cases:
            with self.subTest(profile=invalid), self.assertRaises(ValueError):
                classify(invalid)
        for paths in ([], [""], ["src", "src"]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                freeze_routing(profile(), paths)
        with self.assertRaises(ValueError):
            freeze_routing(profile(), ["."], request_text=1)
        with self.assertRaises(ValueError):
            freeze_routing(profile(), ["."], full_closure_required="yes")
        frozen = freeze_routing(profile(), ["."])
        for invalid in (None, {**frozen, "request_fingerprint": "bad"},
                        {**frozen, "full_closure_required": "yes"}):
            with self.subTest(frozen=invalid), self.assertRaises(ValueError):
                validate_frozen_routing(invalid)

    def test_absolute_roots_cannot_expand_routing_to_the_workspace(self):
        for path in ("/", "///", "\\", "\\\\", "/tmp", "../outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                freeze_routing(profile(), [path])
        for path, expected in ((".", "."), ("./", "."), ("src/", "src"), ("src\\unit", "src/unit")):
            self.assertEqual([expected], freeze_routing(profile(), [path])["allowed_paths"])

    def test_non_boolean_closure_flag_and_bad_assessment_counts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "full_closure_required must be boolean"):
            classify(profile(), full_closure_required="yes")
        with self.assertRaisesRegex(ValueError, "one or two frozen assessments"):
            freeze_routing(profile(), ["."], assessment_count=3)
        frozen = freeze_routing(profile(), ["."])
        with self.assertRaisesRegex(ValueError, "one or two frozen assessments"):
            validate_frozen_routing({**frozen, "assessment_count": 5})

    def test_local_known_task_stays_inline(self):
        self.assertEqual(classify(profile())["route"], "inline")

    def test_explicit_full_closure_forces_a_plan_and_is_exposed_to_the_controller(self):
        result = classify(profile(), full_closure_required=True)

        self.assertTrue(result["full_closure_required"])
        self.assertEqual("planned", result["route"])
        self.assertIn("full_closure_claim", result["reasons"])

    def test_raw_request_does_not_override_explicit_closure_intent(self):
        self.assertFalse(
            freeze_routing(
                profile(), ["."], request_text="不用深度审查，只修复登录问题",
            )["full_closure_required"]
        )

    def test_cli_accepts_explicit_full_closure_without_an_unused_request_file(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("task_profile.py")), "--full-closure"],
            input=json.dumps(profile()), text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("planned", json.loads(result.stdout)["route"])

    def test_cli_rejects_the_removed_request_file_argument(self):
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.txt"
            request_path.write_text("request", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("task_profile.py")),
                 "--request-file", str(request_path)],
                input=json.dumps(profile()), text=True, capture_output=True, check=False,
            )

        self.assertEqual(2, result.returncode)

    def test_unknown_or_cross_service_task_requires_plan(self):
        self.assertEqual(classify(profile(uncertainty="high"))["route"], "planned")
        self.assertEqual(classify(profile(scope="cross-service"))["route"], "planned")

    def test_cross_service_risk_cannot_be_hidden_in_a_local_single_profile(self):
        for invalid in (
            profile(risk_flags=["cross-service"]),
            profile(risk_flags=["cross-service"], scope="cross-service"),
            profile(risk_flags=["cross-service"], scope="cross-service", coupling="dependent"),
        ):
            with self.subTest(profile=invalid), self.assertRaisesRegex(ValueError, "cross-service"):
                classify(invalid)

        valid = profile(
            risk_flags=["cross-service"], scope="cross-service", coupling="dependent",
            verification="external",
        )
        self.assertEqual("planned", classify(valid)["route"])

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
        value = profile(
            scope="cross-service", coupling="dependent", verification="external",
            risk_flags=["cross-service"],
        )

        routing = freeze_routing(value, ["service-a", "service-b"])

        self.assertEqual(3, routing["schema_version"])
        self.assertEqual("planned", routing["route"])
        self.assertEqual("high", routing["review_tier"])
        self.assertTrue(routing["integration_required"])
        self.assertEqual(value, routing["profile"])
        self.assertEqual(64, len(routing["profile_fingerprint"]))

    def test_frozen_routing_binds_an_explicit_closure_decision(self):
        routing = freeze_routing(profile(), ["."], request_text="彻底检查所有问题",
                                 full_closure_required=True)

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
