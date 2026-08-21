#!/usr/bin/env python3
"""Normalize public reviewer results into Converge review state records."""

import argparse
import hashlib
import json
import sys


AXES = {"spec", "quality", "integration"}
PHASES = {"initial", "re_review", "closure"}
STATUSES = {"pass", "findings", "blocked"}


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha256(value, name):
    value = _string(value, name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _finding_fingerprint(finding, legacy):
    if not isinstance(finding, dict):
        raise ValueError("findings[] must be an object")
    value = _string(finding.get("fingerprint"), "findings[].fingerprint")
    for field in ("evidence", "impact", "root_cause"):
        _string(finding.get(field), f"findings[].{field}")
    if finding.get("scope") not in {"current", "pre-existing", "out-of-scope", "task-local"}:
        raise ValueError("findings[].scope is invalid")
    if finding.get("classification") not in {"defect", "suggestion"}:
        raise ValueError("findings[].classification is invalid")
    if not legacy:
        return _sha256(value, "findings[].fingerprint")
    canonical = {
        key: finding.get(key)
        for key in ("fingerprint", "evidence", "impact", "root_cause", "scope", "classification")
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def normalize_result(value, reviewer_ref):
    """Return the exact review request record accepted by Single State v10."""
    if not isinstance(value, dict):
        raise ValueError("review result must be an object")
    version = value.get("protocol_version")
    if version not in {2, 3}:
        raise ValueError("unsupported review protocol_version")
    axis = value.get("axis")
    phase = value.get("phase")
    if axis not in AXES or phase not in PHASES:
        raise ValueError("review axis or phase is invalid")
    source = _sha256(value.get("source_fingerprint"), "source_fingerprint")
    independent = value.get("independent")
    if not isinstance(independent, bool):
        raise ValueError("independent must be boolean")

    legacy = version == 2
    mode = value.get("mode")
    if legacy:
        if mode not in {"intent", "blind"}:
            raise ValueError("review mode is invalid")
        mode = "shared" if mode == "intent" else "blind"
        status = value.get("axis_status")
        if value.get("status") not in {"reviewed", "blocked"} or (
            (value.get("status") == "blocked") != (status == "blocked")
        ):
            raise ValueError("blocked review result is inconsistent")
    else:
        if mode not in {"shared", "blind"}:
            raise ValueError("review mode is invalid")
        status = value.get("status")
    if status not in STATUSES:
        raise ValueError("review status is invalid")

    findings = value.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    if status != "findings" and findings:
        raise ValueError(f"{status} result cannot contain findings")
    fingerprints = [_finding_fingerprint(finding, legacy) for finding in findings]
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("finding fingerprints must be unique")
    if status == "findings" and not fingerprints:
        raise ValueError("findings status requires findings")
    if status == "blocked":
        _string(value.get("blocked_reason"), "blocked_reason")

    return {
        "axis": axis,
        "phase": phase,
        "source_fingerprint": source,
        "status": status,
        "reviewer_ref": _string(reviewer_ref, "reviewer_ref"),
        "mode": mode,
        "independent": independent,
        "finding_fingerprints": fingerprints,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("normalize",))
    parser.add_argument("--input", required=True)
    parser.add_argument("--reviewer-ref", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.input != "-":
            raise ValueError("normalize only accepts --input - from stdin")
        result = normalize_result(json.load(sys.stdin), arguments.reviewer_ref)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, json.JSONDecodeError) as error:
        print(f"review result blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
