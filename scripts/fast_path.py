#!/usr/bin/env python3
"""Issue a bounded receipt for the one-file documentation fast path."""

import argparse
import hashlib
import json
import sys
from pathlib import PurePosixPath

from evidence_contract import run_evidence, valid_evidence_receipts, validate_source_receipt
from task_profile import infer_path_risks


DOCUMENT_SUFFIXES = {".adoc", ".md", ".mdx", ".rst", ".txt"}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_fast_path(source, check, risk_flags):
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
    value = {
        "schema_version": 1,
        "status": "eligible",
        "scope": "local",
        "risk_flags": [],
        "source": source,
        "check": check,
    }
    return {**value, "receipt_fingerprint": fingerprint(value)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--risk-flags", required=True, help="must be JSON []")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    try:
        argv = arguments.argv[1:] if arguments.argv[:1] == ["--"] else arguments.argv
        risk_flags = json.loads(arguments.risk_flags)
        check = run_evidence(arguments.workspace, arguments.baseline, argv)
        receipt = validate_fast_path(check["source"], check, risk_flags)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"fast path blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
