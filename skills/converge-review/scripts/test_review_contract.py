#!/usr/bin/env python3
"""Executable tests for the public review result adapter."""

import sys
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from delivery_next import validate_execution_control
from review_contract import normalize_result


class ReviewContractTest(unittest.TestCase):
    def test_cli_normalizes_stdin_into_the_internal_record(self):
        source = "a" * 64
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("review_contract.py")),
                "normalize",
                "--input",
                "-",
                "--reviewer-ref",
                "reviewer-1",
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

    def test_v2_result_normalizes_to_the_internal_v3_record(self):
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

        record = normalize_result(result, reviewer_ref="reviewer-1")

        self.assertEqual("shared", record["mode"])
        self.assertEqual("findings", record["status"])
        self.assertEqual(64, len(record["finding_fingerprints"][0]))
        validate_execution_control({
            "routing": {
                "schema_version": 1, "status": "frozen", "assessment_count": 1,
                "route": "inline", "review_tier": "normal",
                "profile_fingerprint": "b" * 64,
            },
            "review": {
                "protocol_version": 3, "repair_budget_remaining": 1,
                "re_review_budget_remaining": 1, "integration_budget_remaining": 0,
                "rounds": [{"source_fingerprint": source, "requests": [record]}],
            },
        }, source)

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
            }, reviewer_ref="reviewer-1")


if __name__ == "__main__":
    unittest.main()
