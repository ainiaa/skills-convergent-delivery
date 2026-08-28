#!/usr/bin/env python3
"""Route an observed task profile without subjective scoring."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import PurePosixPath


SCOPES = {"local", "cross-module", "cross-service"}
COUPLINGS = {"single", "dependent", "independent"}
UNCERTAINTIES = {"low", "medium", "high"}
VERIFICATIONS = {"local", "multi-module", "external"}
PROFILE_FIELDS = {
    "schema_version", "assessment_phase", "scope", "coupling", "uncertainty",
    "verification", "risk_flags", "cross_session", "delegable_tasks",
    "context_isolation_benefit",
}
RISK_FLAGS = {
    "money", "payment", "time", "timezone", "sql", "mapper",
    "database-migration", "transaction", "concurrency", "idempotency",
    "public-api", "security", "permission", "sensitive-log", "cross-service",
    "release-contract", "irreversible",
}
PATH_RISK_MARKERS = {
    "sql": (".sql",),
    "database-migration": ("migration", "migrations"),
    "permission": ("permission", "permissions", "authorization", "authz"),
    "security": ("security", "permission", "permissions", "authorization", "authz"),
    "public-api": ("api", "openapi"),
    "money": ("money", "amount"),
    "payment": ("payment", "payments"),
    "transaction": ("transaction", "transactions"),
    "concurrency": ("concurrency", "concurrent", "lock", "locks"),
    "idempotency": ("idempotency", "idempotent"),
    "timezone": ("timezone", "time-zone"),
}
def classify(value, full_closure_required=False):
    if not isinstance(value, dict) or set(value) != PROFILE_FIELDS:
        raise ValueError("task profile fields are invalid")
    if value.get("schema_version") != 2:
        raise ValueError("schema_version must be 2")
    if value.get("assessment_phase") not in {"provisional", "frozen"}:
        raise ValueError("assessment_phase must be provisional or frozen")
    if not isinstance(full_closure_required, bool):
        raise ValueError("full_closure_required must be boolean")
    if value.get("scope") not in SCOPES:
        raise ValueError("scope is invalid")
    if value.get("coupling") not in COUPLINGS:
        raise ValueError("coupling is invalid")
    if value.get("uncertainty") not in UNCERTAINTIES:
        raise ValueError("uncertainty is invalid")
    if value.get("verification") not in VERIFICATIONS:
        raise ValueError("verification is invalid")
    risks = value.get("risk_flags")
    if not isinstance(risks, list) or any(not isinstance(item, str) for item in risks):
        raise ValueError("risk_flags must be a string list")
    if set(risks) - RISK_FLAGS:
        raise ValueError("risk_flags contains an unknown value")
    for field in ("cross_session", "context_isolation_benefit"):
        if not isinstance(value.get(field), bool):
            raise ValueError(f"{field} must be boolean")
    tasks = value["delegable_tasks"]
    if not isinstance(tasks, int) or isinstance(tasks, bool) or tasks < 0:
        raise ValueError("delegable_tasks must be a non-negative integer")

    reasons = []
    if value["cross_session"]:
        recommended_route = "batch"
        reasons.append("cross_session")
    elif value["context_isolation_benefit"] and tasks > 0 and value["coupling"] != "dependent":
        recommended_route = "delegated"
        reasons.append("context_isolation_benefit")
    elif (
        value["scope"] != "local"
        or value["coupling"] != "single"
        or value["uncertainty"] != "low"
        or value["verification"] != "local"
        or tasks > 1
    ):
        recommended_route = "planned"
        for field, simple in (
            ("scope", "local"), ("coupling", "single"),
            ("uncertainty", "low"), ("verification", "local"),
        ):
            if value[field] != simple:
                reasons.append(f"{field}:{value[field]}")
        if tasks > 1:
            reasons.append("multiple_delegable_tasks")
    else:
        recommended_route = "inline"
        reasons.append("bounded_local_task")
    if full_closure_required and recommended_route == "inline":
        recommended_route = "planned"
        reasons.append("full_closure_claim")
    route = recommended_route if value["assessment_phase"] == "frozen" else "planned"
    review_tier = "high" if risks else "low" if recommended_route == "inline" else "normal"
    return {
        "route": route,
        "recommended_route": recommended_route,
        "review_tier": review_tier,
        "assessment_phase": value["assessment_phase"],
        "full_closure_required": full_closure_required,
        "reasons": reasons,
    }


def _canonical_paths(paths):
    if not isinstance(paths, list) or not paths:
        raise ValueError("allowed_paths must be a non-empty list")
    canonical = []
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("allowed_paths must contain non-empty strings")
        path = value.replace("\\", "/").rstrip("/") or "."
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("allowed_paths must stay inside the workspace")
        canonical.append(str(parsed))
    if len(canonical) != len(set(canonical)):
        raise ValueError("allowed_paths must be unique")
    return sorted(canonical)


def _routing_decision(profile, full_closure_required):
    return classify(profile, full_closure_required)


def _routing(profile, allowed_paths, assessment_count, request_fingerprint, full_closure_required):
    decision = _routing_decision(profile, full_closure_required)
    if profile["assessment_phase"] != "frozen" or assessment_count not in {1, 2}:
        raise ValueError("routing requires one or two frozen assessments")
    allowed = _canonical_paths(allowed_paths)
    identity = {
        "profile": profile,
        "allowed_paths": allowed,
        "request_fingerprint": request_fingerprint,
        "full_closure_required": full_closure_required,
    }
    return {
        "schema_version": 3,
        "status": "frozen",
        "assessment_count": assessment_count,
        "route": decision["route"],
        "review_tier": decision["review_tier"],
        "profile": profile,
        "allowed_paths": allowed,
        "integration_required": (
            profile["scope"] == "cross-service" or profile["delegable_tasks"] > 1
        ),
        "request_fingerprint": request_fingerprint,
        "full_closure_required": full_closure_required,
        "profile_fingerprint": hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def freeze_routing(profile, allowed_paths, assessment_count=1, request_text="",
                   full_closure_required=False):
    if not isinstance(request_text, str):
        raise ValueError("request text must be a string")
    if not isinstance(full_closure_required, bool):
        raise ValueError("full_closure_required must be boolean")
    return _routing(
        profile,
        allowed_paths,
        assessment_count,
        hashlib.sha256(request_text.encode("utf-8")).hexdigest(),
        full_closure_required,
    )


def validate_frozen_routing(value):
    if not isinstance(value, dict):
        raise ValueError("routing must be an object")
    request_fingerprint = value.get("request_fingerprint")
    if not isinstance(request_fingerprint, str) or len(request_fingerprint) != 64 \
            or any(char not in "0123456789abcdef" for char in request_fingerprint):
        raise ValueError("routing request_fingerprint must be a lowercase sha256")
    full_closure_required = value.get("full_closure_required")
    if not isinstance(full_closure_required, bool):
        raise ValueError("routing full_closure_required must be boolean")
    return _routing(
        value.get("profile"),
        value.get("allowed_paths"),
        value.get("assessment_count"),
        request_fingerprint,
        full_closure_required,
    )


def infer_path_risks(paths):
    risks = set()
    for value in paths:
        lowered = value.lower()
        parts = set(PurePosixPath(lowered).parts) | set(re.split(r"[^a-z0-9]+", lowered))
        for risk, markers in PATH_RISK_MARKERS.items():
            if any(marker.startswith(".") and lowered.endswith(marker) or marker in parts
                   for marker in markers):
                risks.add(risk)
    return risks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="-")
    parser.add_argument("--request-file", type=argparse.FileType("r"))
    parser.add_argument("--full-closure", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.input != "-":
            raise ValueError("task profile input must use stdin")
        request_text = arguments.request_file.read() if arguments.request_file is not None else ""
        print(json.dumps(classify(json.load(sys.stdin), arguments.full_closure), sort_keys=True))
        return 0
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
