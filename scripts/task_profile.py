#!/usr/bin/env python3
"""Route an observed task profile without subjective scoring."""

import argparse
import json
import sys


SCOPES = {"local", "cross-module", "cross-service"}
COUPLINGS = {"single", "dependent", "independent"}
UNCERTAINTIES = {"low", "medium", "high"}
VERIFICATIONS = {"local", "multi-module", "external"}
HIGH_RISK = {
    "money", "payment", "database-migration", "transaction", "concurrency",
    "idempotency", "public-api", "security", "permission", "irreversible",
}


def classify(value):
    if value.get("assessment_round") not in {1, 2}:
        raise ValueError("assessment_round must be 1 or 2")
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
    tasks = value.get("delegable_tasks", 0)
    if not isinstance(tasks, int) or isinstance(tasks, bool) or tasks < 0:
        raise ValueError("delegable_tasks must be a non-negative integer")

    review_tier = "high" if HIGH_RISK.intersection(risks) else "normal" if risks else "low"
    reasons = []
    if value.get("cross_session") is True:
        route = "batch"
        reasons.append("cross_session")
    elif value.get("context_isolation_benefit") is True and tasks > 0:
        route = "delegated"
        reasons.append("context_isolation_benefit")
    elif (
        value["scope"] != "local"
        or value["coupling"] != "single"
        or value["uncertainty"] != "low"
        or value["verification"] != "local"
        or risks
        or tasks > 1
    ):
        route = "planned"
        reasons.append("planning_signal")
    else:
        route = "inline"
        reasons.append("bounded_local_task")
    return {"route": route, "review_tier": review_tier, "reasons": reasons}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="-")
    arguments = parser.parse_args()
    if arguments.input != "-":
        raise ValueError("task profile input must use stdin")
    try:
        print(json.dumps(classify(json.load(sys.stdin)), sort_keys=True))
        return 0
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
