#!/usr/bin/env python3
"""Emit one safe runtime action for a validated Batch Protocol state."""

import argparse
import json
import sys

from batch_state import validate_state


def next_action(state):
    status = state["status"]
    if status in {"blocked", "complete"}:
        return status

    current = state["current_batch"]
    if current is None:
        return status
    batch = next(item for item in state["batches"] if item["batch_id"] == current)
    batch_status = batch["status"]
    if batch_status == "pending":
        return "dispatch" if status == "active" else status
    if batch_status == "dispatching":
        return "blocked"
    if batch_status == "running":
        return f"query:{batch['worker_ref']}"
    if batch_status == "validating-receipt":
        return "validate-receipt"
    return "blocked"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.input != "-":
            raise ValueError("only --input - is accepted")
        state = json.load(sys.stdin)
        validate_state(state)
        print(next_action(state))
        return 0
    except (KeyError, OSError, StopIteration, ValueError, json.JSONDecodeError) as error:
        print("blocked")
        print(f"batch runtime blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
