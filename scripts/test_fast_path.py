#!/usr/bin/env python3
"""Regression tests for the deterministic fast-path eligibility receipt."""

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evidence_contract
from fast_path import validate_fast_path


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def source(path="docs/guide.md"):
    value = {
        "schema_version": 2,
        "baseline_commit": "a" * 40,
        "commit_id": "b" * 40,
        "tree_hash": "c" * 40,
        "diff_fingerprint": "d" * 64,
        "changed_paths": [path],
        "changed_entries": [{
            "path": path,
            "kind": "file",
            "mode": "100644",
            "content_fingerprint": "e" * 64,
        }],
    }
    return {**value, "source_fingerprint": fingerprint(value)}


def check(source_value):
    value = {
        "schema_version": 2,
        "argv": ["python3", "-m", "markdownlint", "docs/guide.md"],
        "command": "python3 -m markdownlint docs/guide.md",
        "exit_code": 0,
        "stdout_fingerprint": "f" * 64,
        "stderr_fingerprint": "0" * 64,
        "runner_fingerprint": hashlib.sha256(
            (ROOT / "scripts/evidence_contract.py").read_bytes()
        ).hexdigest(),
        "evidence_level": "observed",
        "source": source_value,
    }
    return {**value, "receipt_fingerprint": fingerprint(value)}


class FastPathTest(unittest.TestCase):
    def test_accepts_one_checked_local_markdown_change_with_no_risk(self):
        source_value = source()
        receipt = validate_fast_path(source_value, check(source_value), [])

        self.assertEqual("eligible", receipt["status"])
        self.assertEqual("local", receipt["scope"])
        self.assertEqual([], receipt["risk_flags"])
        self.assertEqual(source_value, receipt["source"])
        self.assertEqual(64, len(receipt["receipt_fingerprint"]))

    def test_rejects_skill_instruction_and_runtime_or_risk_named_paths(self):
        for path, marker in (
            ("SKILL.md", "SKILL.md"),
            ("config/runtime.md", "runtime"),
            ("docs/api.md", "risk"),
        ):
            source_value = source(path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, marker):
                validate_fast_path(source_value, check(source_value), [])

    def test_rejects_attested_risk_or_unbound_check(self):
        source_value = source()
        with self.assertRaisesRegex(ValueError, "risk_flags"):
            validate_fast_path(source_value, check(source_value), ["security"])
        other_source = source("docs/other.md")
        with self.assertRaisesRegex(ValueError, "check"):
            validate_fast_path(source_value, check(other_source), [])


if __name__ == "__main__":
    unittest.main()
