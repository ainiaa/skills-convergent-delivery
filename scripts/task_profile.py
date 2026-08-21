#!/usr/bin/env python3
"""Route an observed task profile without subjective scoring."""

import argparse
import json
import sys


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


def classify(value):
    if not isinstance(value, dict) or set(value) != PROFILE_FIELDS:
        raise ValueError("task profile fields are invalid")
    if value.get("schema_version") != 2:
        raise ValueError("schema_version must be 2")
    if value.get("assessment_phase") not in {"provisional", "frozen"}:
        raise ValueError("assessment_phase must be provisional or frozen")
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
        or risks
        or tasks > 1
    ):
        recommended_route = "planned"
        for field, simple in (
            ("scope", "local"), ("coupling", "single"),
            ("uncertainty", "low"), ("verification", "local"),
        ):
            if value[field] != simple:
                reasons.append(f"{field}:{value[field]}")
        if risks:
            reasons.extend(f"risk:{risk}" for risk in risks)
        if tasks > 1:
            reasons.append("multiple_delegable_tasks")
    else:
        recommended_route = "inline"
        reasons.append("bounded_local_task")
    route = recommended_route if value["assessment_phase"] == "frozen" else "planned"
    review_tier = "high" if risks else "low" if recommended_route == "inline" else "normal"
    return {
        "route": route,
        "recommended_route": recommended_route,
        "review_tier": review_tier,
        "assessment_phase": value["assessment_phase"],
        "reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="-")
    arguments = parser.parse_args()
    try:
        if arguments.input != "-":
            raise ValueError("task profile input must use stdin")
        print(json.dumps(classify(json.load(sys.stdin)), sort_keys=True))
        return 0
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
