#!/usr/bin/env python3
"""Read-only completion gate for an explicitly armed Converge run."""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from delivery_next import upgrade_state, validate_active_lease, validate_state
from run_contract import delivery_action


def allow(terminal):
    return {"decision": "allow", "terminal": terminal}


def decide(payload, lease_root=None):
    if not isinstance(payload, dict) or payload.get("schema_version") != 11:
        return allow("inactive")
    autonomy = payload.get("execution_control", {}).get("autonomy")
    if not isinstance(autonomy, dict) or autonomy.get("enabled") is not True:
        return allow("inactive")
    state = upgrade_state(payload)
    stage = validate_state(state, SimpleNamespace(strict_evidence=True))
    if stage in {"complete", "blocked"}:
        return allow(stage)
    if lease_root is not None:
        validate_active_lease(state, SimpleNamespace(
            lease_root=lease_root, run_id=state["run_id"], writer_id=state["writer_id"],
        ))
    return {
        "decision": "block",
        "next_action": delivery_action(stage, state["task_key"], state.get("blocked_reason")),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    arguments = parser.parse_args()
    path = Path(arguments.state)
    if not path.exists():
        print(json.dumps(allow("inactive"), sort_keys=True))
        return 0
    try:
        decision = decide(json.loads(path.read_text(encoding="utf-8")))
        print(json.dumps(decision, sort_keys=True))
        return 2 if decision["decision"] == "block" else 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"decision": "block", "reason": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
