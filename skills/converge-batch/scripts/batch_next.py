#!/usr/bin/env python3
"""Emit one safe runtime action for a validated Batch Protocol state."""

import argparse
import json
import sys
from pathlib import Path

from batch_state import validate_state

ROOT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(ROOT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ROOT_SCRIPTS))
from run_contract import action, legacy_action


def next_action(state):
    status = state["status"]
    if status in {"blocked", "complete"}:
        task_id = state["plan"]["plan_id"]
        return (
            action("block", task_id=task_id, reason=state["blocked_reason"])
            if status == "blocked" else action("complete", task_id=task_id)
        )

    current = state["current_batch"]
    if current is None:
        return action("block", task_id=state["plan"]["plan_id"], reason="active plan has no current batch")
    batch = next(item for item in state["batches"] if item["batch_id"] == current)
    task_id = batch.get("task_id", batch["batch_id"])
    batch_status = batch["status"]
    if batch_status == "pending":
        return action("dispatch", task_id=task_id) if status == "active" else action("block", task_id=task_id, reason="plan is not active")
    if batch_status == "dispatching":
        return action("block", task_id=task_id, reason="dispatch outcome is uncertain")
    if batch_status == "running":
        return (
            action("query", task_id=task_id, worker_ref=batch["worker_ref"])
            if batch.get("worker_status") in {None, "working"}
            else action("block", task_id=task_id, reason="running batch has a terminal worker")
        )
    if batch_status == "validating-receipt":
        worker_status = batch.get("worker_status")
        if worker_status == "working":
            return action("query", task_id=task_id, worker_ref=batch["worker_ref"])
        return action("verify", task_id=task_id, target="receipt") if worker_status == "completed" else action("block", task_id=task_id, reason="worker did not complete")
    return action("block", task_id=task_id, reason="batch state has no safe next action")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--format", choices=("json", "legacy"), default="json")
    arguments = parser.parse_args()
    state = None
    try:
        if arguments.input != "-":
            raise ValueError("only --input - is accepted")
        state = json.load(sys.stdin)
        validate_state(state)
        result = next_action(state)
        print(legacy_action(result) if arguments.format == "legacy" else json.dumps(result, sort_keys=True))
        return 0
    except (KeyError, OSError, StopIteration, ValueError, json.JSONDecodeError) as error:
        task_id = (
            state.get("plan", {}).get("plan_id") if isinstance(state, dict) else None
        ) or "unknown-plan"
        result = action("block", task_id=task_id, reason=str(error))
        print("blocked" if arguments.format == "legacy" else json.dumps(result, sort_keys=True))
        print(f"batch runtime blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
