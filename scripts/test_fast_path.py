#!/usr/bin/env python3
"""Regression tests for the deterministic fast-path eligibility receipt."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evidence_contract
from fast_path import validate_fast_path


SCRIPT = ROOT / "scripts" / "fast_path.py"
LEASE_SCRIPT = ROOT / "scripts" / "delivery_lease.py"


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


def lease():
    value = {
        "schema_version": 1,
        "run_id": "run-1",
        "writer_id": "writer-1",
        "lease_expires_at": "2099-01-01T00:00:00Z",
        "lease_fingerprint": "1" * 64,
    }
    return value


class FastPathTest(unittest.TestCase):
    def test_accepts_one_checked_local_markdown_change_with_no_risk(self):
        source_value = source()
        receipt = validate_fast_path(source_value, check(source_value), [], lease())

        self.assertEqual("eligible", receipt["status"])
        self.assertEqual("local", receipt["scope"])
        self.assertEqual([], receipt["risk_flags"])
        self.assertEqual(source_value, receipt["source"])
        self.assertEqual(lease(), receipt["lease"])
        self.assertEqual(64, len(receipt["receipt_fingerprint"]))

    def test_rejects_skill_instruction_and_runtime_or_risk_named_paths(self):
        for path, marker in (
            ("SKILL.md", "SKILL.md"),
            ("config/runtime.md", "runtime"),
            ("docs/api.md", "risk"),
        ):
            source_value = source(path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, marker):
                validate_fast_path(source_value, check(source_value), [], lease())

    def test_rejects_attested_risk_or_unbound_check(self):
        source_value = source()
        with self.assertRaisesRegex(ValueError, "risk_flags"):
            validate_fast_path(source_value, check(source_value), ["security"], lease())
        other_source = source("docs/other.md")
        with self.assertRaisesRegex(ValueError, "check"):
            validate_fast_path(source_value, check(other_source), [], lease())

    def test_rejects_invalid_or_missing_lease_attestation(self):
        source_value = source()
        for value in ({}, {**lease(), "lease_fingerprint": "g" * 64}, {
            **lease(), "lease_expires_at": "2000-01-01T00:00:00Z",
        }):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "lease"):
                validate_fast_path(source_value, check(source_value), [], value)

    def test_cli_requires_an_owned_active_lease_and_a_format_only_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            self.git(workspace, "init")
            self.git(workspace, "config", "user.email", "fast@example.test")
            self.git(workspace, "config", "user.name", "Fast Path")
            document = workspace / "docs" / "guide.md"
            document.parent.mkdir()
            document.write_text("# Guide\\n\\nText\\n", encoding="utf-8")
            self.git(workspace, "add", ".")
            self.git(workspace, "commit", "-m", "baseline")
            document.write_text("# Guide\\n\\nText  \\n", encoding="utf-8")

            lease_root = Path(directory) / "leases"
            common_dir = (workspace / ".git").resolve()
            acquired = subprocess.run(
                [
                    sys.executable, str(LEASE_SCRIPT), "acquire", "--root", str(lease_root),
                    "--repo", str(common_dir), "--workspace", str(workspace),
                    "--task-key", "fast-path", "--run-id", "run-1", "--writer-id", "writer-1",
                ], text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, acquired.returncode, acquired.stderr)
            command = [
                sys.executable, str(SCRIPT), "--workspace", str(workspace), "--baseline", "HEAD",
                "--risk-flags", "[]", "--lease-root", str(lease_root), "--repo", str(common_dir),
                "--task-key", "fast-path", "--run-id", "run-1", "--writer-id", "writer-1",
                "--", sys.executable, "-c", "pass",
            ]
            eligible = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(0, eligible.returncode, eligible.stderr)
            self.assertEqual("eligible", json.loads(eligible.stdout)["status"])

            mutating_check = [
                *command[:command.index("--") + 1], sys.executable, "-c",
                "from pathlib import Path; Path('docs/guide.md').write_text('mutated\\n')",
            ]
            blocked_mutation = subprocess.run(mutating_check, text=True, capture_output=True, check=False)
            self.assertEqual(2, blocked_mutation.returncode)
            self.assertIn("modified source", blocked_mutation.stderr)

            document.write_text("# Guide\\n\\nText  \\n", encoding="utf-8")

            blocked_owner = subprocess.run(
                [*command[:command.index("--writer-id") + 1], "writer-2", *command[command.index("--") :]],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(2, blocked_owner.returncode)
            self.assertIn("lease", blocked_owner.stderr)

            document.write_text("# Guide\\n\\nDifferent text\\n", encoding="utf-8")
            blocked_content = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(2, blocked_content.returncode)
            self.assertIn("format-only", blocked_content.stderr)

            self.git(workspace, "checkout", "--", "docs/guide.md")
            (workspace / "docs" / "new.md").write_text("# New document\\n", encoding="utf-8")
            blocked_untracked = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(2, blocked_untracked.returncode)
            self.assertIn("tracked", blocked_untracked.stderr)

    def git(self, workspace, *arguments):
        result = subprocess.run(
            ["git", "-C", str(workspace), *arguments], text=True, capture_output=True, check=False
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result


if __name__ == "__main__":
    unittest.main()
