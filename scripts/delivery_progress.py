#!/usr/bin/env python3
"""Create bounded parent-trusted worker progress receipts and render them."""

import argparse
import copy
import datetime
import json
import sys


EVENTS = {"heartbeat", "milestone"}
PHASES = {
    "understanding", "planning", "reproducing", "testing", "implementing",
    "verifying", "reviewing", "closing",
}
TEXT_LIMITS = {"milestone": 200, "activity": 300, "evidence": 300, "next_action": 200}


def bounded_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    value = " ".join(value.split())
    if len(value) > TEXT_LIMITS[name]:
        raise ValueError(f"{name} exceeds {TEXT_LIMITS[name]} characters")
    return value


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def apply_event(state, worker_ref, event, phase, milestone, activity, evidence, next_action, now=None):
    if event not in EVENTS:
        raise ValueError("event must be heartbeat or milestone")
    if phase not in PHASES:
        raise ValueError("phase is invalid")
    updated = copy.deepcopy(state)
    workers = [worker for worker in updated.get("workers", []) if worker.get("ref") == worker_ref]
    if len(workers) != 1 or workers[0].get("status") != "working":
        raise ValueError("worker must identify one active worker")
    previous = workers[0].get("progress") or {}
    sequence = previous.get("sequence", 0) + 1
    objective_revision = previous.get("objective_revision", 0) + (event == "milestone")
    workers[0]["progress"] = {
        "sequence": sequence,
        "objective_revision": objective_revision,
        "event": event,
        "phase": phase,
        "milestone": bounded_text(milestone, "milestone"),
        "activity": bounded_text(activity, "activity"),
        "evidence": bounded_text(evidence, "evidence"),
        "next_action": bounded_text(next_action, "next_action"),
        "observed_at": now or utc_now(),
    }
    updated["revision"] = updated.get("revision", -1) + 1
    return updated


def render_status(state):
    rows = []
    for worker in state.get("workers", []):
        progress = worker.get("progress") or {}
        rows.append(
            " | ".join(
                (
                    str(worker.get("ref", "?")),
                    str(worker.get("status", "?")),
                    str(progress.get("phase", "waiting")),
                    str(progress.get("milestone", "No progress receipt yet")),
                    str(progress.get("next_action", "Await update")),
                )
            )
        )
    return "\n".join(rows) if rows else "No active workers"


def read_stdin():
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg}") from error


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    event = subparsers.add_parser("event")
    event.add_argument("--worker-ref", required=True)
    event.add_argument("--event", choices=sorted(EVENTS), required=True)
    event.add_argument("--phase", choices=sorted(PHASES), required=True)
    event.add_argument("--milestone", required=True)
    event.add_argument("--activity", required=True)
    event.add_argument("--evidence", required=True)
    event.add_argument("--next-action", required=True)
    subparsers.add_parser("status")
    arguments = parser.parse_args()
    try:
        state = read_stdin()
        if arguments.command == "event":
            print(json.dumps(apply_event(
                state, arguments.worker_ref, arguments.event, arguments.phase,
                arguments.milestone, arguments.activity, arguments.evidence,
                arguments.next_action,
            ), ensure_ascii=False, sort_keys=True))
        else:
            print(render_status(state))
        return 0
    except ValueError as error:
        print(f"progress failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
