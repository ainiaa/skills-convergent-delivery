#!/usr/bin/env python3
"""Explicitly arm one active Schema v10 run for autonomous delivery."""

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

from delivery_next import validate_state
from multi_model import resolve


def _argv(value, name):
    if not isinstance(value, list) or not value or any(
            not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"service autonomy requires a frozen {name} argv")
    return value


def arm(state, requirements, acceptance, runtime="hook", service_runner=None, verification_argv=None,
        audit_argv=None):
    if not isinstance(state, dict) or state.get("schema_version") != 10:
        raise ValueError("only an active Schema v10 state can be explicitly armed")
    if state.get("status") != "active":
        raise ValueError("only an active state can be armed")
    if not requirements or not acceptance:
        raise ValueError("autonomous arming requires requirement and acceptance items")
    updated = copy.deepcopy(state)
    updated["revision"] += 1
    routing = updated["execution_control"]["routing"]
    items = [
        *({"id": f"requirement-{index}", "kind": "requirement", "value": value}
          for index, value in enumerate(requirements, 1)),
        *({"id": f"scope-{index}", "kind": "scope", "value": value}
          for index, value in enumerate(routing["allowed_paths"], 1)),
        *({"id": f"acceptance-{index}", "kind": "acceptance", "value": value}
          for index, value in enumerate(acceptance, 1)),
    ]
    updated["schema_version"] = 11
    runtime_value = {"mode": "hook"}
    if runtime == "service":
        if routing["review_tier"] != "low":
            raise ValueError("service autonomy supports only low-risk routes")
        profiles = resolve(None, workspace=updated["workspace"])
        profile = profiles["roles"]["implementer"]
        if service_runner is not None and profile["runner_id"] != service_runner:
            raise ValueError("selected service runner does not match the frozen implementer profile")
        verification_argv = _argv(verification_argv, "verification")
        audit_argv = _argv(audit_argv, "independent audit")
        if audit_argv == verification_argv:
            raise ValueError("service autonomy requires an independent audit argv")
        runtime_value = {
            "mode": "service", "runner_profile": profile, "max_cycles": 5,
            "verification_argv": verification_argv, "audit_argv": audit_argv,
        }
    elif runtime != "hook" or service_runner is not None or verification_argv is not None or audit_argv is not None:
        raise ValueError("autonomy runtime is invalid")
    updated["execution_control"] = {
        **updated["execution_control"],
        "autonomy": {
            "schema_version": 1,
            "enabled": True,
            "manifest": {"source_fingerprint": updated["source_fingerprint"], "items": items},
            "audit_batches": [],
            "repair_budget_remaining": 1,
            "re_audit_budget_remaining": 1,
            "runtime": runtime_value,
            "action_attempts": [],
        },
    }
    validate_state(updated, argparse.Namespace(strict_evidence=True))
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--requirement", action="append", default=[])
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--runtime", choices=("hook", "service"), default="hook")
    parser.add_argument("--service-runner", choices=("codex-exec-v1", "claude-code-v1"))
    parser.add_argument("--verification-argv")
    parser.add_argument("--audit-argv")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--lease-root")
    parser.add_argument("--state-root")
    parser.add_argument("--repo-id")
    parser.add_argument("--task-key")
    parser.add_argument("--run-id")
    parser.add_argument("--writer-id")
    parser.add_argument("--expected-revision", type=int)
    arguments = parser.parse_args()
    try:
        state = json.loads(Path(arguments.state).read_text(encoding="utf-8"))
        verification_argv = (
            json.loads(arguments.verification_argv) if arguments.verification_argv is not None else None
        )
        audit_argv = json.loads(arguments.audit_argv) if arguments.audit_argv is not None else None
        candidate = arm(state, arguments.requirement, arguments.acceptance,
                        arguments.runtime, arguments.service_runner, verification_argv, audit_argv)
        if not arguments.write:
            print(json.dumps(candidate, sort_keys=True))
            return 0
        required = ("lease_root", "state_root", "repo_id", "task_key", "run_id", "writer_id")
        if any(getattr(arguments, name) is None for name in required) \
                or arguments.expected_revision is None:
            raise ValueError("--write requires lease, state, owner, task, and expected revision")
        command = [
            sys.executable, str(Path(__file__).with_name("delivery_state.py")), "write", "--input", "-",
            "--lease-root", arguments.lease_root, "--state-root", arguments.state_root,
            "--repo-id", arguments.repo_id, "--task-key", arguments.task_key,
            "--run-id", arguments.run_id, "--writer-id", arguments.writer_id,
            "--expected-revision", str(arguments.expected_revision),
        ]
        result = subprocess.run(
            command, input=json.dumps(candidate), text=True, capture_output=True, check=False,
        )
        if result.returncode:
            raise ValueError(result.stderr.strip() or "autonomy arm write failed")
        print(result.stdout, end="")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"autonomy arm blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
