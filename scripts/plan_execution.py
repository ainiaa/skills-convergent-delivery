#!/usr/bin/env python3
"""Choose a safe next action after validating an authorized implementation plan."""

import argparse
import json

from run_contract import action


TOOLING_FAILURE_MARKERS = (
    "closure path has no indexed files",
    "CodeGraph requires a fresh index and verified graph bindings",
    "CodeGraph query failed or timed out",
    "planned graph receipt is unavailable",
)


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def classify_validation_failure(reason):
    """Keep known observation gaps separate from invalid plans and safety gates."""
    reason = _string(reason, "validation failure")
    if any(marker in reason for marker in TOOLING_FAILURE_MARKERS):
        return {"status": "uncovered", "kind": "tooling", "reason": reason}
    return {"status": "blocked", "reason": reason}


def _validation(value):
    if not isinstance(value, dict):
        raise ValueError("validation result must be an object")
    if value == {"status": "valid"}:
        return value
    if value.get("status") == "uncovered" and set(value) == {"status", "kind", "reason"} \
            and value["kind"] == "tooling":
        _string(value["reason"], "validation reason")
        return value
    if value.get("status") == "blocked" and set(value) == {"status", "reason"}:
        _string(value["reason"], "validation reason")
        return value
    raise ValueError("validation result is invalid")


def decide(task_id, *, implementation_authorized, validation):
    """Return one action; only an authorized, known tooling gap may continue."""
    task_id = _string(task_id, "task_id")
    if not isinstance(implementation_authorized, bool):
        raise ValueError("implementation_authorized must be boolean")
    validation = _validation(validation)
    if validation["status"] == "blocked":
        return {"status": "blocked", "reason": validation["reason"]}
    if not implementation_authorized:
        return {"status": "blocked", "reason": "implementation_authorization_required"}
    return {
        "status": "execute",
        "next_action": action("execute-inline", task_id=task_id, phase="implementation"),
        "uncovered_reason": validation.get("reason"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--implementation-authorized", action="store_true")
    parser.add_argument("--validation-error")
    arguments = parser.parse_args()
    validation = (
        classify_validation_failure(arguments.validation_error)
        if arguments.validation_error is not None else {"status": "valid"}
    )
    print(json.dumps(decide(
        arguments.task_id,
        implementation_authorized=arguments.implementation_authorized,
        validation=validation,
    ), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
