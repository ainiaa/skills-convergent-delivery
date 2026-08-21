#!/usr/bin/env python3
"""Create bounded parent-trusted worker progress receipts and render them."""

import argparse
import copy
import datetime
import hashlib
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


def worker_milestone(state, worker_ref, event, phase, milestone, activity, evidence, next_action, now=None):
    if event != "milestone":
        raise ValueError("worker objective event must be milestone")
    return apply_event(
        state, worker_ref, event, phase, milestone, activity, evidence, next_action, now
    )


def parent_observation(state, worker_ref, host_status, evidence, now=None):
    if host_status != "working":
        raise ValueError("heartbeat requires a working host observation")
    workers = [worker for worker in state.get("workers", []) if worker.get("ref") == worker_ref]
    if len(workers) != 1 or workers[0].get("status") != "working":
        raise ValueError("worker must identify one active worker")
    previous = workers[0].get("progress")
    if previous is None:
        return apply_event(
            state, worker_ref, "heartbeat", "understanding", "Worker is running",
            "Host query confirms activity", evidence, "Wait for an objective milestone", now,
        )
    return apply_event(
        state, worker_ref, "heartbeat", previous["phase"], previous["milestone"],
        previous["activity"], evidence, previous["next_action"], now,
    )


PHASE_LABELS = {
    "understanding": "正在理解",
    "planning": "正在规划",
    "reproducing": "正在复现",
    "testing": "正在测试",
    "implementing": "正在实现",
    "verifying": "正在验证",
    "reviewing": "正在评审",
    "closing": "正在收尾",
}


def render_status_update(state, previous_fingerprint=None):
    lines = []
    for worker in state.get("workers", []):
        receipt = worker.get("progress") or {}
        phase = PHASE_LABELS.get(receipt.get("phase"), "等待进度")
        milestone = receipt.get("milestone", "尚无客观里程碑")
        next_action = receipt.get("next_action", "等待更新")
        lines.append(
            f"{worker.get('ref', '?')}：状态={worker.get('status', '?')}；"
            f"{phase}；{milestone}；下一步：{next_action}"
        )
    rendered = "\n".join(lines) if lines else "当前没有活动 worker"
    fingerprint = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return ("" if fingerprint == previous_fingerprint else rendered), fingerprint


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
    event.add_argument("--event", choices=("milestone",), required=True)
    event.add_argument("--phase", choices=sorted(PHASES), required=True)
    event.add_argument("--milestone", required=True)
    event.add_argument("--activity", required=True)
    event.add_argument("--evidence", required=True)
    event.add_argument("--next-action", required=True)
    observe = subparsers.add_parser("observe")
    observe.add_argument("--worker-ref", required=True)
    observe.add_argument("--host-status", choices=("working",), required=True)
    observe.add_argument("--evidence", required=True)
    subparsers.add_parser("status")
    arguments = parser.parse_args()
    try:
        state = read_stdin()
        if arguments.command == "event":
            print(json.dumps(worker_milestone(
                state, arguments.worker_ref, arguments.event, arguments.phase,
                arguments.milestone, arguments.activity, arguments.evidence,
                arguments.next_action,
            ), ensure_ascii=False, sort_keys=True))
        elif arguments.command == "observe":
            print(json.dumps(parent_observation(
                state, arguments.worker_ref, arguments.host_status, arguments.evidence,
            ), ensure_ascii=False, sort_keys=True))
        else:
            print(render_status(state))
        return 0
    except ValueError as error:
        print(f"progress failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
