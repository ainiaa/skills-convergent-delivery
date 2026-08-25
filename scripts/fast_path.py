#!/usr/bin/env python3
"""Issue a bounded receipt for the one-file documentation fast path."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from delivery_lease import active_lease_attestation, canonical_path, lease_paths
from evidence_contract import (
    run_evidence, valid_evidence_receipts, validate_source_receipt, workspace_source,
)
from task_profile import infer_path_risks


DOCUMENT_SUFFIXES = {".adoc", ".md", ".mdx", ".rst", ".txt"}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_lease(lease):
    fields = {
        "schema_version", "run_id", "writer_id", "lease_expires_at", "lease_fingerprint"
    }
    if not isinstance(lease, dict) or set(lease) != fields or lease.get("schema_version") != 1:
        raise ValueError("fast path lease attestation is invalid")
    if not all(isinstance(lease.get(field), str) and lease[field] for field in (
        "run_id", "writer_id", "lease_expires_at", "lease_fingerprint"
    )) or len(lease["lease_fingerprint"]) != 64 \
            or any(character not in "0123456789abcdef" for character in lease["lease_fingerprint"]):
        raise ValueError("fast path lease attestation is invalid")
    try:
        expires_at = datetime.fromisoformat(lease["lease_expires_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("fast path lease attestation is invalid") from error
    if expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
        raise ValueError("fast path lease attestation is invalid")
    return lease


def validate_format_only_workspace(workspace, baseline, source):
    """Reject every semantic or untracked change before issuing the fast-path receipt."""
    source = validate_source_receipt(source)
    workspace = Path(workspace).expanduser().resolve()
    path = source["changed_paths"][0]
    tracked = subprocess.run(
        ["git", "-C", str(workspace), "ls-files", "--error-unmatch", "--", path],
        capture_output=True, check=False,
    )
    if tracked.returncode != 0:
        raise ValueError("fast path requires one tracked documentation file")
    result = subprocess.run(
        [
            "git", "-C", str(workspace), "diff", "--no-ext-diff", "--no-textconv",
            "--ignore-all-space", "--exit-code", baseline, "--", path,
        ],
        capture_output=True, check=False,
    )
    if result.returncode == 1:
        raise ValueError("fast path requires a format-only diff")
    if result.returncode != 0:
        raise ValueError("fast path could not verify the format-only diff")


def validate_fast_path(source, check, risk_flags, lease):
    """Accept only a checked, single-file, non-contract documentation change."""
    source = validate_source_receipt(source)
    if risk_flags != []:
        raise ValueError("fast path requires risk_flags=[]")
    paths = source["changed_paths"]
    if len(paths) != 1:
        raise ValueError("fast path requires exactly one changed file")
    entry = source["changed_entries"][0]
    path = PurePosixPath(paths[0])
    if path.name == "SKILL.md":
        raise ValueError("fast path excludes SKILL.md behavior instructions")
    if entry["kind"] != "file" or entry["mode"] != "100644" or path.suffix.lower() not in DOCUMENT_SUFFIXES:
        raise ValueError("fast path requires one plain documentation file")
    risks = infer_path_risks(paths)
    if risks or any("runtime" in part.lower() for part in path.parts):
        raise ValueError("fast path path has inferred runtime or risk markers")
    if not valid_evidence_receipts([check], source):
        raise ValueError("fast path check must be a successful receipt bound to the source")
    lease = validate_lease(lease)
    value = {
        "schema_version": 2,
        "status": "eligible",
        "scope": "local",
        "risk_flags": [],
        "source": source,
        "check": check,
        "lease": lease,
    }
    return {**value, "receipt_fingerprint": fingerprint(value)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--risk-flags", required=True, help="must be JSON []")
    parser.add_argument("--lease-root", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--writer-id", required=True)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    try:
        argv = arguments.argv[1:] if arguments.argv[:1] == ["--"] else arguments.argv
        risk_flags = json.loads(arguments.risk_flags)
        workspace = canonical_path(arguments.workspace)
        repo = canonical_path(arguments.repo)
        paths = lease_paths(arguments.lease_root, repo, workspace, arguments.task_key)
        active_lease_attestation(
            paths, repo, workspace, arguments.task_key, arguments.run_id, arguments.writer_id
        )
        source_before_check = workspace_source(workspace, arguments.baseline)
        check = run_evidence(arguments.workspace, arguments.baseline, argv)
        if check["source"] != source_before_check:
            raise ValueError("fast path check modified source")
        validate_format_only_workspace(workspace, arguments.baseline, check["source"])
        lease = active_lease_attestation(
            paths, repo, workspace, arguments.task_key, arguments.run_id, arguments.writer_id
        )
        receipt = validate_fast_path(check["source"], check, risk_flags, lease)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"fast path blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
