import subprocess
import tempfile
import unittest
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

        self.assertEqual(1, source["schema_version"])
        self.assertEqual(self.baseline, source["baseline_commit"])
        self.assertEqual(["committed.txt", "working.txt"], source["changed_paths"])

    def test_pass_receipt_must_match_the_exact_source_receipt(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        receipt = {
            "schema_version": 1,
            "command": "python3 test.py",
            "exit_code": 0,
            "source": source,
        }

        self.assertTrue(evidence_contract.valid_evidence_receipts([receipt], source))
        self.assertFalse(
            evidence_contract.valid_evidence_receipts(
                [{**receipt, "schema_version": 2}], source
            )
        )


if __name__ == "__main__":
    unittest.main()
