#!/usr/bin/env python3
"""Executable tests for the public review result adapter."""

import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from delivery_next import validate_execution_control
from task_profile import freeze_routing
from review_contract import normalize_request, normalize_result, request_fingerprint


def review_request(axis="spec", phase="initial", mode="shared", source="a" * 64):
    return {
        "protocol_version": 3,
        "task_id": "task-123",
        "axis": axis,
        "phase": phase,
        "mode": mode,
        "acceptance": ["Requested behavior"],
        "allowed_scope": ["scripts"],
        "baseline_commit": "b" * 40,
        "source_fingerprint": source,
        "prior_findings": [],
    }


class ReviewContractTest(unittest.TestCase):
    def test_cli_normalizes_stdin_into_the_internal_record(self):
        source = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(json.dumps(review_request()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("review_contract.py")),
                    "normalize",
                    "--input",
                    "-",
                    "--reviewer-ref",
                    "reviewer-1",
                    "--request-file",
                    str(request_path),
                ],
                input=json.dumps({
                    "protocol_version": 3,
                    "mode": "shared",
                    "axis": "spec",
                    "phase": "initial",
                    "source_fingerprint": source,
                    "independent": False,
                    "status": "pass",
                    "findings": [],
                    "blocked_reason": None,
                }),
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("reviewer-1", json.loads(result.stdout)["reviewer_ref"])
        self.assertEqual("pass", json.loads(result.stdout)["status"])
        self.assertEqual("task-123", json.loads(result.stdout)["task_id"])
        self.assertEqual(64, len(json.loads(result.stdout)["request_fingerprint"]))

    def test_request_bounds_reject_unbounded_external_input(self):
        for field, value in (
            ("task_id", "x" * 201),
            ("acceptance", ["a"] * 33),
            ("allowed_scope", ["scripts"] * 65),
            ("prior_findings", ["finding"] * 17),
        ):
            with self.subTest(field=field):
                request = review_request()
                request[field] = value
                with self.assertRaises(ValueError):
                    normalize_request(request)

    def test_re_review_requires_the_original_finding_fingerprint(self):
        request = review_request(axis="quality", phase="re_review", mode="blind")

        with self.assertRaisesRegex(ValueError, "prior_findings"):
            normalize_request(request)

        request["prior_findings"] = ["b" * 64]
        self.assertEqual(["b" * 64], normalize_request(request)["prior_findings"])

    def test_re_review_can_report_a_new_scoped_finding_after_binding_the_prior_one(self):
        request = review_request(axis="quality", phase="re_review", mode="blind", source="c" * 64)
        request["prior_findings"] = ["b" * 64]
        result = normalize_result({
            "protocol_version": 3,
            "mode": "blind",
            "axis": "quality",
            "phase": "re_review",
            "source_fingerprint": "c" * 64,
            "independent": True,
            "status": "findings",
            "findings": [{
                "fingerprint": "d" * 64,
                "evidence": "scripts/example.py:10 violates frozen acceptance",
                "impact": "the repaired diff still has a scoped defect",
                "root_cause": "the repair missed a shared path",
                "scope": "current",
                "classification": "defect",
            }],
            "blocked_reason": None,
        }, reviewer_ref="reviewer-1", request=request)

        self.assertEqual(["d" * 64], result["finding_fingerprints"])

    def test_integration_pass_can_preserve_task_local_findings(self):
        result = normalize_result({
            "protocol_version": 3,
            "mode": "blind",
            "axis": "integration",
            "phase": "initial",
            "source_fingerprint": "a" * 64,
            "independent": True,
            "status": "pass",
            "findings": [{
                "fingerprint": "b" * 64,
                "evidence": "scripts/example.py:10 has a local concern",
                "impact": "does not affect the integration path",
                "root_cause": "single-task validation is incomplete",
                "scope": "task-local",
                "classification": "suggestion",
            }],
            "blocked_reason": None,
        }, reviewer_ref="reviewer-1", request=review_request(
            axis="integration", mode="blind"
        ))

        self.assertEqual("pass", result["status"])
        self.assertEqual(["b" * 64], result["finding_fingerprints"])

    def test_integration_pass_cannot_hide_a_cross_task_finding(self):
        with self.assertRaisesRegex(ValueError, "pass result cannot contain findings"):
            normalize_result({
                "protocol_version": 3,
                "mode": "blind",
                "axis": "integration",
                "phase": "initial",
                "source_fingerprint": "a" * 64,
                "independent": True,
                "status": "pass",
                "findings": [{
                    "fingerprint": "b" * 64,
                    "evidence": "scripts/example.py:10 breaks a shared contract",
                    "impact": "the integration path is incorrect",
                    "root_cause": "contract mapping is incomplete",
                    "scope": "current",
                    "classification": "defect",
                }],
                "blocked_reason": None,
            }, reviewer_ref="reviewer-1", request=review_request(
                axis="integration", mode="blind"
            ))

    def test_normalize_result_keeps_bounded_structured_findings_for_recovery(self):
        result = normalize_result({
            "protocol_version": 3,
            "mode": "shared",
            "axis": "spec",
            "phase": "initial",
            "source_fingerprint": "a" * 64,
            "independent": False,
            "status": "findings",
            "findings": [{
                "fingerprint": "b" * 64,
                "evidence": "scripts/example.py:10 fails the acceptance check",
                "impact": "completion would report a false pass",
                "root_cause": "the acceptance receipt is not source-bound",
                "scope": "current",
                "classification": "defect",
            }],
            "blocked_reason": None,
        }, reviewer_ref="reviewer-1", request=review_request())

        self.assertEqual(["b" * 64], result["finding_fingerprints"])
        self.assertEqual("completion would report a false pass", result["finding_records"][0]["impact"])

    def test_legacy_result_schema_is_rejected(self):
        source = "a" * 64
        result = {
            "protocol_version": 2,
            "mode": "intent",
            "axis": "spec",
            "phase": "initial",
            "source_fingerprint": source,
            "independent": False,
            "status": "reviewed",
            "axis_status": "findings",
            "findings": [{
                "fingerprint": "flow + violated behavior + root cause",
                "evidence": "test.py:10 fails",
                "impact": "completion can be false",
                "root_cause": "evidence is not bound",
                "scope": "current",
                "classification": "defect",
            }],
            "blocked_reason": None,
        }

        with self.assertRaisesRegex(ValueError, "protocol_version must be 3"):
            normalize_result(result, reviewer_ref="reviewer-1", request=review_request(source=source))

    def test_blocked_result_cannot_claim_findings(self):
        with self.assertRaisesRegex(ValueError, "blocked"):
            normalize_result({
                "protocol_version": 3,
                "mode": "blind",
                "axis": "quality",
                "phase": "initial",
                "source_fingerprint": "a" * 64,
                "independent": True,
                "status": "blocked",
                "findings": [{"fingerprint": "b" * 64}],
                "blocked_reason": "missing source",
            }, reviewer_ref="reviewer-1", request=review_request(axis="quality", mode="blind"))

    def test_blocked_result_preserves_its_recovery_reason(self):
        result = normalize_result({
            "protocol_version": 3,
            "mode": "shared",
            "axis": "spec",
            "phase": "initial",
            "source_fingerprint": "a" * 64,
            "independent": False,
            "status": "blocked",
            "findings": [],
            "blocked_reason": "frozen source is unavailable",
        }, reviewer_ref="reviewer-1", request=review_request())

        self.assertEqual("frozen source is unavailable", result["blocked_reason"])

    def test_initial_quality_and_integration_results_must_be_independent_blind_reviews(self):
        for axis in ("quality", "integration"):
            with self.subTest(axis=axis), self.assertRaisesRegex(ValueError, "independent blind"):
                normalize_result({
                    "protocol_version": 3,
                    "mode": "shared",
                    "axis": axis,
                    "phase": "initial",
                    "source_fingerprint": "a" * 64,
                    "independent": False,
                    "status": "pass",
                    "findings": [],
                    "blocked_reason": None,
                }, reviewer_ref="reviewer-1", request=review_request(axis=axis, mode="shared"))

    def test_result_must_match_the_frozen_request(self):
        result = {
            "protocol_version": 3,
            "mode": "shared",
            "axis": "spec",
            "phase": "initial",
            "source_fingerprint": "c" * 64,
            "independent": False,
            "status": "pass",
            "findings": [],
            "blocked_reason": None,
        }

        with self.assertRaisesRegex(ValueError, "request"):
            normalize_result(result, "reviewer-1", review_request(source="a" * 64))

    def test_request_and_result_reject_malformed_identities_and_findings(self):
        self.assertEqual(64, len(request_fingerprint(review_request())))
        for field, value, message in (
            ("baseline_commit", "a" * 39, "Git object"),
            ("source_fingerprint", "A" * 64, "sha256"),
            ("prior_findings", ["a" * 64, "a" * 64], "unique"),
        ):
            with self.subTest(field=field):
                request = review_request()
                request[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    normalize_request(request)

        result = {
            "protocol_version": 3, "mode": "shared", "axis": "spec", "phase": "initial",
            "source_fingerprint": "a" * 64, "independent": False,
            "status": "findings", "findings": [{
                "fingerprint": "b" * 64, "evidence": "proof", "impact": "impact",
                "root_cause": "cause", "scope": "outside", "classification": "defect",
            }], "blocked_reason": None,
        }
        with self.assertRaisesRegex(ValueError, "scope"):
            normalize_result(result, "reviewer-1", review_request())
        result["findings"] = []
        with self.assertRaisesRegex(ValueError, "requires findings"):
            normalize_result(result, "reviewer-1", review_request())

    def test_result_boundary_rejections_and_cli_errors_are_explicit(self):
        result = {
            "protocol_version": 3, "mode": "shared", "axis": "spec", "phase": "initial",
            "source_fingerprint": "a" * 64, "independent": False,
            "status": "findings", "findings": [{
                "fingerprint": "b" * 64, "evidence": "proof", "impact": "impact",
                "root_cause": "cause", "scope": "current", "classification": "defect",
            }], "blocked_reason": None,
        }
        cases = (
            ([], "object"),
            ({**result, "axis": "unknown"}, "axis"),
            ({**result, "phase": "unknown"}, "phase"),
            ({**result, "independent": "false"}, "boolean"),
            ({**result, "mode": "unknown"}, "mode"),
            ({**result, "status": "unknown"}, "status"),
            ({**result, "findings": {}}, "list"),
            ({**result, "findings": [
                result["findings"][0], result["findings"][0],
            ]}, "unique"),
            ({**result, "findings": [None]}, "object"),
            ({**result, "findings": [{"fingerprint": "b" * 64}]}, "fields"),
            ({**result, "findings": [{**result["findings"][0], "evidence": "x" * 501}]}, "non-empty"),
        )
        for invalid, message in cases:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, message):
                normalize_result(invalid, "reviewer-1", review_request())

        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(json.dumps(review_request()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(Path(__file__).with_name("review_contract.py")), "normalize",
                    "--input", str(request_path), "--reviewer-ref", "reviewer-1",
                    "--request-file", str(request_path),
                ], text=True, capture_output=True, check=False,
            )
        self.assertEqual(2, result.returncode)
        self.assertIn("only accepts", result.stderr)


if __name__ == "__main__":
    unittest.main()
