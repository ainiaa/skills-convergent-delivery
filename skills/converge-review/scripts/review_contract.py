#!/usr/bin/env python3
"""Normalize public reviewer results into Converge review state records."""

import argparse
import hashlib
import json
import sys


AXES = {"spec", "quality", "integration"}
PHASES = {"initial", "re_review", "closure"}
STATUSES = {"pass", "findings", "blocked"}
REQUEST_FIELDS = {
    "protocol_version", "task_id", "axis", "phase", "mode", "acceptance",
    "allowed_scope", "baseline_commit", "source_fingerprint", "prior_findings",
}


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha256(value, name):
    value = _string(value, name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _finding_record(finding):
    if not isinstance(finding, dict):
        raise ValueError("findings[] must be an object")
    fields = {
        "fingerprint", "evidence", "impact", "root_cause", "scope", "classification",
    }
    if set(finding) != fields:
        raise ValueError("findings[] fields are invalid")
    record = {
        "fingerprint": _sha256(finding.get("fingerprint"), "findings[].fingerprint"),
        "evidence": _string(finding.get("evidence"), "findings[].evidence"),
        "impact": _string(finding.get("impact"), "findings[].impact"),
        "root_cause": _string(finding.get("root_cause"), "findings[].root_cause"),
        "scope": finding.get("scope"),
        "classification": finding.get("classification"),
    }
    if any(len(record[field]) > 500 for field in ("evidence", "impact", "root_cause")):
        raise ValueError("findings[] text must be at most 500 characters")
    if record["scope"] not in {"current", "pre-existing", "out-of-scope", "task-local"}:
        raise ValueError("findings[].scope is invalid")
    if record["classification"] not in {"defect", "suggestion"}:
        raise ValueError("findings[].classification is invalid")
    return record


def _strings(value, name, *, non_empty=False):
    if not isinstance(value, list) or (non_empty and not value):
        raise ValueError(f"{name} must be a{' non-empty' if non_empty else ''} string list")
    return [_string(item, f"{name}[]") for item in value]


def normalize_request(value):
    if not isinstance(value, dict) or set(value) != REQUEST_FIELDS:
        raise ValueError("review request fields are invalid")
    if value.get("protocol_version") != 3 or value.get("axis") not in AXES \
            or value.get("phase") not in PHASES or value.get("mode") not in {"shared", "blind"}:
        raise ValueError("review request identity is invalid")
    request = {
        **value,
        "task_id": _string(value.get("task_id"), "request.task_id"),
        "acceptance": _strings(value.get("acceptance"), "request.acceptance", non_empty=True),
        "allowed_scope": _strings(
            value.get("allowed_scope"), "request.allowed_scope", non_empty=True
        ),
        "baseline_commit": _string(value.get("baseline_commit"), "request.baseline_commit"),
        "source_fingerprint": _sha256(
            value.get("source_fingerprint"), "request.source_fingerprint"
        ),
        "prior_findings": _strings(value.get("prior_findings"), "request.prior_findings"),
    }
    if len(request["baseline_commit"]) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in request["baseline_commit"]
    ):
        raise ValueError("request.baseline_commit must be a full Git object id")
    return request


def request_fingerprint(value):
    request = normalize_request(value)
    return hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def normalize_result(value, reviewer_ref, request):
    """Return the exact review request record accepted by Single State v10."""
    if not isinstance(value, dict):
        raise ValueError("review result must be an object")
    version = value.get("protocol_version")
    if version != 3:
        raise ValueError("review protocol_version must be 3")
    request = normalize_request(request)
    axis = value.get("axis")
    phase = value.get("phase")
    if axis not in AXES or phase not in PHASES:
        raise ValueError("review axis or phase is invalid")
    source = _sha256(value.get("source_fingerprint"), "source_fingerprint")
    independent = value.get("independent")
    if not isinstance(independent, bool):
        raise ValueError("independent must be boolean")

    mode = value.get("mode")
    if mode not in {"shared", "blind"}:
        raise ValueError("review mode is invalid")
    status = value.get("status")
    if any(value.get(field) != request[field] for field in ("axis", "phase", "source_fingerprint")) \
            or mode != request["mode"]:
        raise ValueError("review result does not match the frozen request")
    if phase == "initial" and axis in {"quality", "integration"} \
            and (mode != "blind" or not independent):
        raise ValueError(f"initial {axis} review must be independent blind")
    if status not in STATUSES:
        raise ValueError("review status is invalid")

    findings = value.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    if status != "findings" and findings:
        raise ValueError(f"{status} result cannot contain findings")
    records = [_finding_record(finding) for finding in findings]
    fingerprints = [record["fingerprint"] for record in records]
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("finding fingerprints must be unique")
    if status == "findings" and not fingerprints:
        raise ValueError("findings status requires findings")
    if status == "blocked":
        _string(value.get("blocked_reason"), "blocked_reason")

    return {
        "task_id": request["task_id"],
        "request_fingerprint": request_fingerprint(request),
        "axis": axis,
        "phase": phase,
        "source_fingerprint": source,
        "status": status,
        "reviewer_ref": _string(reviewer_ref, "reviewer_ref"),
        "mode": mode,
        "independent": independent,
        "finding_fingerprints": fingerprints,
        "finding_records": records,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("normalize",))
    parser.add_argument("--input", required=True)
    parser.add_argument("--reviewer-ref", required=True)
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.input != "-":
            raise ValueError("normalize only accepts --input - from stdin")
        result = normalize_result(
            json.load(sys.stdin), arguments.reviewer_ref, json.loads(arguments.request)
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, json.JSONDecodeError) as error:
        print(f"review result blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
