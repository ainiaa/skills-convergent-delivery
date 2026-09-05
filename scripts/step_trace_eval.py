#!/usr/bin/env python3
"""Evaluate an annotated step trace without executing actions."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def evaluate(trace):
    """Check ordering and plan synchronization; annotations cannot prove UI rendering."""
    fields = {"schema_version", "evidence_level", "steps", "completed_before", "events"}
    if not isinstance(trace, dict) or set(trace) != fields \
            or type(trace["schema_version"]) is not int or trace["schema_version"] != 1 \
            or trace["evidence_level"] not in ("fixture", "evaluator_attested"):
        raise ValueError("invalid step trace envelope")
    steps, completed, events = trace["steps"], trace["completed_before"], trace["events"]
    if not isinstance(steps, list) or not steps or len(steps) > 1000 \
            or any(not isinstance(step, str) or not step.strip() for step in steps) \
            or len(set(steps)) != len(steps) \
            or not isinstance(completed, list) or completed != steps[:len(completed)] \
            or not isinstance(events, list) or len(events) > 10000:
        raise ValueError("invalid steps, completed prefix, or events")
    extra = {"start": {"visible"}, "edit": set(), "verify": {"result"},
             "report": {"visible", "result"}}
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("kind"), str) \
                or event["kind"] not in extra \
                or set(event) - {"plan"} != {"step", "kind"} | extra[event["kind"]] \
                or event["step"] not in steps \
                or "visible" in event and type(event["visible"]) is not bool \
                or event["kind"] == "verify" and event["result"] not in ("pass", "fail", "unknown") \
                or event["kind"] == "report" and event["result"] not in ("done", "blocked"):
            raise ValueError("invalid step event")
        if "plan" in event:
            plan = event["plan"]
            if event["kind"] not in ("start", "report") or not isinstance(plan, dict) \
                    or set(plan) - {"fallback", "projection"} != {"capability", "result", "receipt_ref", "fallback_disclosed"} \
                    or plan["capability"] not in ("available", "unavailable", "unknown") \
                    or plan["result"] not in ("success", "failed", "unknown", "not_called") \
                    or type(plan["fallback_disclosed"]) is not bool \
                    or plan["receipt_ref"] is not None and (
                        not isinstance(plan["receipt_ref"], str) or not plan["receipt_ref"].strip()) \
                    or plan["capability"] != "available" and plan["result"] != "not_called" \
                    or plan["result"] == "not_called" and plan["receipt_ref"] is not None:
                raise ValueError("invalid plan observation")
            if "fallback" in plan:
                from delivery_next import validate_host_sync
                validate_host_sync({"mode": "text", "acknowledged_fingerprint": None,
                                    "evidence_level": "controller_attested", "fallback": plan["fallback"]})
            if "projection" in plan:
                projection = plan["projection"]
                if plan["result"] != "success" or not isinstance(projection, list) \
                        or len(projection) != len(steps) \
                        or any(not isinstance(item, dict) or set(item) != {"step", "status"}
                               or item["step"] != step
                               or item["status"] not in ("pending", "in_progress", "completed")
                               for item, step in zip(projection, steps)):
                    raise ValueError("invalid native plan projection")

    binding = hashlib.sha256(json.dumps(trace, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()

    modes = set()
    display_uncovered = False
    failed_sync_fallback = False
    persistent_fallback = None
    native_receipts = {}

    def result(status, violation=None):
        return {"status": status, "violations": [] if violation is None else [violation],
                "trace_fingerprint": binding, "evidence_level": trace["evidence_level"],
                "display_mode": next(iter(modes)) if len(modes) == 1 else "mixed" if modes else "unknown",
                "native_ui_status": "uncovered", "release_status": "uncovered"}

    cursor, active, verified, blocked = len(completed), None, False, False
    for index, event in enumerate(events):
        step, kind = event["step"], event["kind"]
        if kind in ("start", "report"):
            plan = event.get("plan")
            if plan is not None and "fallback" in plan:
                if persistent_fallback is not None and persistent_fallback != plan["fallback"]:
                    return result("fail", f"event {index}: persisted fallback evidence changed")
                persistent_fallback = plan["fallback"]
            if plan is None:
                display_uncovered = True
                modes.add("unknown")
            elif plan["capability"] == "available" and plan["result"] == "not_called" \
                    and not (failed_sync_fallback or persistent_fallback):
                return result("fail", f"event {index}: available native plan tool was not called")
            elif plan["result"] == "success":
                if persistent_fallback is not None:
                    return result("fail", f"event {index}: persisted text mode cannot switch to native")
                modes.add("native")
                projection, receipt = plan.get("projection"), plan["receipt_ref"]
                display_uncovered |= receipt is None or projection is None
                if projection is not None:
                    if receipt is not None:
                        if receipt in native_receipts and native_receipts[receipt] != projection:
                            return result("fail", f"event {index}: native receipt describes conflicting projections")
                        native_receipts[receipt] = projection
                    position = steps.index(step)
                    statuses = [item["status"] for item in projection]
                    expected = "in_progress" if kind == "start" else \
                        "completed" if event["result"] == "done" else "pending"
                    suffix = ["pending"] * (len(steps) - position - 1)
                    allowed_suffixes = [suffix]
                    if kind == "report" and event["result"] == "done" and suffix:
                        allowed_suffixes.append(["in_progress", *suffix[1:]])
                    if statuses[:position] != ["completed"] * position \
                            or statuses[position] != expected \
                            or statuses[position + 1:] not in allowed_suffixes:
                        return result("fail", f"event {index}: native projection does not match step state")
                failed_sync_fallback = False
            else:
                modes.add("text")
                if not plan["fallback_disclosed"]:
                    return result("fail", f"event {index}: text fallback was not disclosed")
                if plan["result"] in ("failed", "unknown"):
                    failed_sync_fallback = True
                    display_uncovered |= plan["receipt_ref"] is None
        if blocked:
            return result("fail", f"event {index}: action after blocked report")
        if kind == "start":
            if active is not None or cursor == len(steps) or step != steps[cursor]:
                return result("fail", f"event {index}: step started before prior result or repeated completed work")
            if not event["visible"]:
                return result("fail", f"event {index}: step start is not user-visible")
            active, verified = step, False
        elif active != step:
            return result("fail", f"event {index}: action outside the active visible step")
        elif kind == "edit":
            verified = False
        elif kind == "verify":
            verified = event["result"] == "pass"
        elif kind == "report":
            if not event["visible"]:
                return result("fail", f"event {index}: step result is not user-visible")
            if event["result"] == "done":
                if not verified:
                    return result("fail", f"event {index}: completion lacks passing verification after the last edit")
                cursor, active = cursor + 1, None
            else:
                blocked = True
    if not events or display_uncovered:
        return result("uncovered")
    return result("pass" if blocked or cursor == len(steps) else "uncovered")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="annotated trace JSON, or stdin")
    args = parser.parse_args()
    try:
        if args.input == "-":
            raw = sys.stdin.buffer.read(1_048_577)
        else:
            with Path(args.input).open("rb") as stream:
                raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("step trace exceeds 1 MiB")
        output = evaluate(json.loads(raw))
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0 if output["status"] == "pass" else 1
    except (OSError, ValueError) as error:
        print(f"step trace rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
