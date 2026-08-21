#!/usr/bin/env python3
"""Negotiate host worker controls without inventing unavailable capabilities."""

import argparse
import json
import sys


PROFILES = {"codex", "claude-code", "single-context"}
CAPABILITIES = ("dispatch", "query", "wait", "interrupt", "tree_query", "restrict_dispatch")
STATUS_MAP = {
    "working": "working",
    "running": "working",
    "pending": "working",
    "timeout": "working",
    "done": "completed",
    "completed": "completed",
    "cancelled": "interrupted",
    "canceled": "interrupted",
    "interrupted": "interrupted",
    "failed": "blocked",
    "blocked": "blocked",
}


def negotiate(profile, observed):
    if profile not in PROFILES:
        raise ValueError("unknown runtime profile")
    if not isinstance(observed, dict) or set(observed) - set(CAPABILITIES):
        raise ValueError("observed capabilities are invalid")
    if any(not isinstance(value, bool) for value in observed.values()):
        raise ValueError("observed capabilities must be booleans")
    if profile == "single-context":
        return {"profile": profile, "mode": "manual", "capabilities": [], "reason": "single context has no recoverable worker"}
    if not observed.get("dispatch") or not observed.get("query"):
        return {"profile": profile, "mode": "manual", "capabilities": [], "reason": "automatic workers require dispatch and stable query"}
    if not observed.get("tree_query") and not observed.get("restrict_dispatch"):
        return {"profile": profile, "mode": "manual", "capabilities": [], "reason": "automatic workers require subtree query or enforced leaf workers"}
    return {
        "profile": profile,
        "mode": "automatic",
        "capabilities": [name for name in CAPABILITIES if observed.get(name)],
        "reason": "host exposes a stable dispatch and query contract",
    }


def normalize_status(status):
    normalized = STATUS_MAP.get(str(status).strip().lower())
    if normalized is None:
        raise ValueError("unknown host status")
    return normalized


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("negotiate", "normalize"))
    parser.add_argument("--profile", choices=sorted(PROFILES))
    parser.add_argument("--status")
    arguments = parser.parse_args()
    try:
        if arguments.command == "normalize":
            if not arguments.status:
                raise ValueError("normalize requires --status")
            print(normalize_status(arguments.status))
        else:
            if not arguments.profile:
                raise ValueError("negotiate requires --profile")
            observed = json.load(sys.stdin)
            print(json.dumps(negotiate(arguments.profile, observed), sort_keys=True))
        return 0
    except (ValueError, json.JSONDecodeError) as error:
        print(f"runtime adapter blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
