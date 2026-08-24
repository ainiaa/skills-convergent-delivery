#!/usr/bin/env python3
"""Deterministic selection and bounded bookkeeping for Converge evaluation."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


REQUIRED = {
    "acceptance", "touched_control_surfaces", "control_source", "candidate_source",
    "allowed_scope", "critical_decisions", "sample_receipts", "revisions",
}
SAMPLE_FIELDS = {
    "schema_version", "scenario_id", "scenario_class", "control_source",
    "candidate_source", "judge_fingerprint", "worker_ref", "evidence_source",
    "evidence_fingerprint", "control_result", "candidate_result", "receipt_fingerprint",
}
SCENARIO_CLASSES = {"known_acceptance", "history", "exploration"}
EVIDENCE_FIELDS = SAMPLE_FIELDS - {
    "evidence_source", "evidence_fingerprint", "receipt_fingerprint",
}


def _string_list(value, name, allow_empty=False):
    if not isinstance(value, list) or (not allow_empty and not value) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return value


def _sample_receipt(value, control_source, candidate_source, artifact_root):
    if not isinstance(value, dict) or set(value) != SAMPLE_FIELDS \
            or value.get("schema_version") != 2:
        raise ValueError("sample receipt fields are invalid")
    for field in ("scenario_id", "worker_ref", "evidence_source"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"sample receipt {field} must be a non-empty string")
    if value["scenario_class"] not in SCENARIO_CLASSES:
        raise ValueError("sample receipt scenario_class is invalid")
    if value["control_source"] != control_source or value["candidate_source"] != candidate_source:
        raise ValueError("sample receipt source does not match the evaluation request")
    for field in ("judge_fingerprint", "evidence_fingerprint", "receipt_fingerprint"):
        fingerprint = value[field]
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 \
                or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError(f"sample receipt {field} is invalid")
    if value["control_result"] not in {"pass", "fail"} \
            or value["candidate_result"] not in {"pass", "fail"}:
        raise ValueError("sample receipt results are invalid")
    identity = {key: item for key, item in value.items() if key != "receipt_fingerprint"}
    expected = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if value["receipt_fingerprint"] != expected:
        raise ValueError("sample receipt fingerprint is invalid")
    evidence = Path(value["evidence_source"])
    if not evidence.is_absolute():
        evidence = artifact_root / evidence
    if not evidence.is_file() or hashlib.sha256(evidence.read_bytes()).hexdigest() \
            != value["evidence_fingerprint"]:
        raise ValueError("sample receipt evidence fingerprint is invalid")
    try:
        evidence_identity = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("sample receipt evidence identity is invalid") from error
    if not isinstance(evidence_identity, dict) or set(evidence_identity) != EVIDENCE_FIELDS \
            or any(evidence_identity[field] != value[field] for field in EVIDENCE_FIELDS):
        raise ValueError("sample receipt evidence identity does not match the receipt")
    return value


def evaluate(request, catalog_path):
    if not isinstance(request, dict) or set(request) != REQUIRED:
        raise ValueError("evaluation request fields are invalid")
    acceptance = _string_list(request["acceptance"], "acceptance")
    touched = set(_string_list(request["touched_control_surfaces"], "touched_control_surfaces"))
    allowed_scope = _string_list(request["allowed_scope"], "allowed_scope")
    decisions = _string_list(request["critical_decisions"], "critical_decisions", True)
    for field in ("control_source", "candidate_source"):
        if not isinstance(request[field], str) or not request[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    samples = request["sample_receipts"]
    if not isinstance(samples, list) or not samples:
        raise ValueError("sample_receipts must be a non-empty list")
    samples = [
        _sample_receipt(
            item, request["control_source"], request["candidate_source"],
            Path(catalog_path).resolve().parent.parent,
        )
        for item in samples
    ]
    fingerprints = [item["receipt_fingerprint"] for item in samples]
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("sample receipts must be unique")
    artifact_root = Path(catalog_path).resolve().parent.parent
    evidence_sources = [
        str((Path(item["evidence_source"]) if Path(item["evidence_source"]).is_absolute()
             else artifact_root / item["evidence_source"]).resolve())
        for item in samples
    ]
    if len(evidence_sources) != len(set(evidence_sources)):
        raise ValueError("sample receipts must use distinct evidence artifacts")
    if len({item["judge_fingerprint"] for item in samples}) != 1:
        raise ValueError("sample receipts must use one frozen judge")
    minimum = 3 if decisions else 1
    if len({item["worker_ref"] for item in samples}) < minimum:
        raise ValueError(f"evaluation requires at least {minimum} fresh samples")

    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    history = [
        entry for entry in catalog.get("escaped_defects", [])
        if touched.intersection(entry.get("control_surfaces", []))
    ]
    expected = {
        *(f"known_acceptance:{item}" for item in acceptance),
        *(f"history:{item['id']}" for item in history),
    }
    observed = {
        f"{item['scenario_class']}:{item['scenario_id']}"
        for item in samples
        if item["scenario_class"] != "exploration"
    }
    if decisions:
        workers_by_scenario = {
            scenario: {
                item["worker_ref"] for item in samples
                if f"{item['scenario_class']}:{item['scenario_id']}" == scenario
            }
            for scenario in expected
        }
        for scenario, workers in sorted(workers_by_scenario.items()):
            if len(workers) < minimum:
                raise ValueError(f"{scenario} requires at least {minimum} fresh workers")
    uncovered = sorted(expected - observed)
    exploration = sorted({
        item["scenario_id"] for item in samples
        if item["scenario_class"] == "exploration"
    })
    def distribution(items):
        results = [item["candidate_result"] for item in items]
        pass_count = results.count("pass")
        pass_rate = pass_count / len(items) if items else 0.0
        return {
            "sample_count": len(items),
            "pass_count": pass_count,
            "fail_count": len(items) - pass_count,
            "pass_rate": pass_rate,
            "variance": pass_rate * (1 - pass_rate),
        }

    gating_samples = [item for item in samples if item["scenario_class"] != "exploration"]
    exploration_samples = [item for item in samples if item["scenario_class"] == "exploration"]
    sample_distribution = distribution(samples)
    gating_distribution = distribution(gating_samples)
    exploration_distribution = distribution(exploration_samples)
    pairs = [(item["control_result"], item["candidate_result"]) for item in gating_samples]
    differential = {
        "regressions": pairs.count(("pass", "fail")),
        "fixes": pairs.count(("fail", "pass")),
        "both_pass": pairs.count(("pass", "pass")),
        "both_fail": pairs.count(("fail", "fail")),
    }

    revisions = request["revisions"]
    if not isinstance(revisions, list) or len(revisions) > 3:
        raise ValueError("revisions must contain at most three entries")
    if not all(
        isinstance(item, dict)
        and set(item) == {
            "before_failing_samples", "after_failing_samples",
            "before_variance", "after_variance",
        }
        and all(
            isinstance(item[field], int)
            and not isinstance(item[field], bool)
            and item[field] >= 0
            for field in ("before_failing_samples", "after_failing_samples")
        )
        and all(
            isinstance(item[field], (int, float))
            and not isinstance(item[field], bool)
            and 0 <= item[field] <= 0.25
            for field in ("before_variance", "after_variance")
        )
        for item in revisions
    ):
        raise ValueError("revision metrics are invalid")
    stop_reason = "evidence_gap" if uncovered else (
        "complete" if gating_distribution["fail_count"] == 0 else "failed"
    )
    revisions_used = len(revisions)
    for index, revision in enumerate(revisions):
        improved = revision["after_failing_samples"] < revision["before_failing_samples"] or (
            revision["after_failing_samples"] == revision["before_failing_samples"]
            and revision["after_variance"] < revision["before_variance"]
        )
        if not improved:
            stop_reason = "no_improvement"
            revisions_used = index + 1
            break

    return {
        "control_source": request["control_source"],
        "candidate_source": request["candidate_source"],
        "touched_control_surfaces": sorted(touched),
        "known_acceptance": acceptance,
        "history": history,
        "exploration": exploration,
        "uncovered": uncovered,
        "allowed_scope": allowed_scope,
        "sample_distribution": sample_distribution,
        "gating_distribution": gating_distribution,
        "exploration_distribution": exploration_distribution,
        "differential": differential,
        "revisions_used": revisions_used,
        "stop_reason": stop_reason,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--catalog", required=True)
    arguments = parser.parse_args()
    try:
        request = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        print(json.dumps(evaluate(request, arguments.catalog), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"evaluation blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
