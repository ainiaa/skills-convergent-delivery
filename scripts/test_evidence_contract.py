import json
import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path

import evidence_contract


class EvidenceContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.name", "Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "seed.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "commit", "-q", "-m", "seed"],
            check=True,
        )
        self.baseline = subprocess.run(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def tearDown(self):
        self.temporary.cleanup()

    def test_source_receipt_is_versioned_and_uses_the_frozen_baseline(self):
        (self.workspace / "committed.txt").write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "committed.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "commit", "-q", "-m", "task"],
            check=True,
        )
        (self.workspace / "working.txt").write_text("working\n", encoding="utf-8")

        source = evidence_contract.workspace_source(self.workspace, self.baseline)

        self.assertEqual(2, source["schema_version"])
        self.assertEqual(self.baseline, source["baseline_commit"])
        self.assertEqual(["committed.txt", "working.txt"], source["changed_paths"])
        self.assertEqual(
            ["committed.txt", "working.txt"],
            [entry["path"] for entry in source["changed_entries"]],
        )

    def test_source_identity_includes_file_type_and_mode(self):
        path = self.workspace / "tool.sh"
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        before = evidence_contract.workspace_source(self.workspace, self.baseline)

        os.chmod(path, 0o755)
        after = evidence_contract.workspace_source(self.workspace, self.baseline)

        self.assertNotEqual(before["source_fingerprint"], after["source_fingerprint"])
        self.assertEqual("100755", after["changed_entries"][0]["mode"])

    def test_pass_receipt_is_created_by_running_argv_and_matches_the_exact_source(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "print('verified')"]
        )

        self.assertEqual(receipt, evidence_contract.validate_observed_evidence_receipt(receipt))
        self.assertTrue(evidence_contract.valid_evidence_receipts([receipt], source))
        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual([sys.executable, "-c", "print('verified')"], receipt["argv"])
        self.assertFalse(
            evidence_contract.valid_evidence_receipts(
                [{**receipt, "receipt_fingerprint": "0" * 64}], source
            )
        )

    def test_observed_receipt_keeps_a_real_failure_for_tdd_red_evidence(self):
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "raise SystemExit(1)"]
        )

        self.assertEqual(1, evidence_contract.validate_observed_evidence_receipt(receipt)["exit_code"])
        self.assertFalse(evidence_contract.valid_evidence_receipts([receipt], receipt["source"]))

    def test_nonexistent_command_cannot_be_turned_into_a_passing_receipt(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)

        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, ["definitely-not-a-real-command"]
        )

        self.assertEqual(127, receipt["exit_code"])
        self.assertFalse(evidence_contract.valid_evidence_receipts([receipt], source))

    def test_timeout_becomes_a_non_passing_receipt(self):
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout_seconds=0.01,
        )

        self.assertEqual(124, receipt["exit_code"])

    def test_cli_executes_the_command_without_a_shell(self):
        marker = self.workspace / "marker.txt"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(evidence_contract.__file__)),
                "run",
                "--workspace",
                str(self.workspace),
                "--baseline",
                self.baseline,
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ran", marker.read_text(encoding="utf-8"))
        self.assertEqual(0, json.loads(result.stdout)["exit_code"])

    def test_sensitive_command_arguments_are_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "sensitive"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, ["tool", "--api-key=secret-value"]
            )

        with self.assertRaisesRegex(ValueError, "sensitive"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, ["curl", "Authorization: Bearer secret-value"]
            )

    def test_receipts_reject_oversized_argv_values(self):
        with self.assertRaisesRegex(ValueError, "argv"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, [sys.executable, "-c", "x" * 4097]
            )

    def test_source_receipt_validator_rejects_tampered_metadata(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        source["changed_paths"] = ["invented.txt"]

        with self.assertRaisesRegex(ValueError, "paths|fingerprint"):
            evidence_contract.validate_source_receipt(source)


if __name__ == "__main__":
    unittest.main()
