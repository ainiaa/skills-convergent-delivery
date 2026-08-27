#!/usr/bin/env python3
"""Create and arm the one state that a Codex Stop Hook may continue."""

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

from delivery_engine import controller_identity, provider_reference
from delivery_state import DEFAULT_STATE_ROOT, state_path
from evidence_contract import workspace_source
from autonomy_arm import arm
from provider_contract import canonical_fingerprint
from task_profile import freeze_routing, infer_path_risks


def _git(workspace, *arguments):
    result = subprocess.run(["git", "-C", str(workspace), *arguments], text=True,
                            capture_output=True, check=False)
    if result.returncode or not result.stdout.strip():
        raise ValueError("autonomy begin requires a Git workspace")
    return result.stdout.strip()


def _task_key(workspace, baseline, scope, acceptance):
    value = json.dumps({"workspace": str(workspace), "baseline": baseline,
                        "scope": sorted(scope), "acceptance": sorted(acceptance)},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "task-" + hashlib.sha256(value.encode()).hexdigest()


def _is_linked_worktree(workspace):
    git_dir = Path(_git(workspace, "rev-parse", "--git-dir")).resolve()
    common_dir = Path(_git(workspace, "rev-parse", "--git-common-dir")).resolve()
    return git_dir != common_dir


def _release_lease(arguments, state):
    result = subprocess.run(
        [
            sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "release",
            "--root", arguments.lease_root, "--state-root", arguments.state_root,
            "--repo", state["repo_id"], "--workspace", state["workspace"],
            "--task-key", state["task_key"], "--run-id", state["run_id"],
            "--writer-id", state["writer_id"],
        ],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown release failure"
        raise ValueError(f"autonomy lease cleanup failed: {detail}")
    try:
        outcome = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("autonomy lease cleanup returned invalid output") from error
    if outcome != {"status": "released"}:
        raise ValueError("autonomy lease cleanup failed")


def initial_state(workspace, requirements, acceptance, scope, run_id, writer_id, risk_flags=None):
    workspace = Path(workspace).expanduser().resolve()
    baseline = _git(workspace, "rev-parse", "HEAD")
    source = workspace_source(workspace, baseline)
    profile = {
        "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
        "coupling": "single", "uncertainty": "low", "verification": "local",
        "risk_flags": sorted(set(infer_path_risks(source["changed_paths"])) | set(risk_flags or [])),
        "cross_session": False, "delegable_tasks": 0, "context_isolation_benefit": False,
    }
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference("native-v1", "feature"),
        "stage_providers": {},
    }
    task_key = _task_key(workspace, baseline, scope, acceptance)
    return {
        "schema_version": 10, "run_id": run_id, "repo_id": str(workspace),
        "task_key": task_key, "writer_id": writer_id, "revision": 0,
        "workspace": str(workspace),
        "baseline": {"commit": baseline, "diff_fingerprint": source["diff_fingerprint"]},
        "scope_fingerprint": hashlib.sha256(
            json.dumps({"requirements": requirements, "scope": scope, "acceptance": acceptance},
                       ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "source_fingerprint": source["source_fingerprint"], "source_receipt": source,
        "execution_control": {
            "routing": freeze_routing(profile, scope),
            "review": {
                "protocol_version": 3, "repair_budget_remaining": 1,
                "re_review_budget_remaining": 1, "integration_budget_remaining": 0,
                "rounds": [{"source_fingerprint": source["source_fingerprint"], "requests": []}],
            },
        },
        "controller": controller_identity(),
        "provider_binding": {
            "selection": "explicit", "reason": "autonomy begin freezes native controller",
            "task_kind": "feature", "binding": binding,
            "binding_fingerprint": canonical_fingerprint(binding),
        },
        "current_stage": "scope", "requires_stability_round": False, "status": "active",
        "ledger": {
            "completed_rounds": 0, "repair_fingerprints": [], "checks": [],
            "acceptance": [
                {"criterion": item, "evidence": "pending", "result": "unknown",
                 "freshness": "unavailable", "source_fingerprint": source["source_fingerprint"]}
                for item in acceptance
            ],
        },
        "handoff": {
            "goal": "; ".join(requirements), "last_verification": "not yet run",
            "open_issues": [], "next_action": "execute frozen scope action",
        },
        "workers": [], "worker_tree_receipt": None, "runtime_binding": None,
        "host_sync": {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        },
    }


def run(arguments):
    workspace = Path(arguments.workspace).expanduser().resolve()
    requirements = [item.strip() for item in arguments.requirement if item.strip()]
    acceptance = [item.strip() for item in arguments.acceptance if item.strip()]
    scope = [item.strip() for item in arguments.scope if item.strip()]
    if not requirements:
        raise ValueError("autonomy begin requires a requirement")
    if not acceptance:
        raise ValueError("autonomy begin requires an acceptance criterion")
    if not scope:
        raise ValueError("autonomy begin requires a scope")
    if arguments.runtime == "service" and not _is_linked_worktree(workspace):
        raise ValueError("service autonomy requires an isolated Git worktree")
    if arguments.runtime == "service" and (
            Path(arguments.state_root).expanduser().resolve() != DEFAULT_STATE_ROOT.resolve()
            or Path(arguments.lease_root).expanduser().resolve()
            != (Path.home() / ".convergent-delivery" / "leases").resolve()
    ):
        raise ValueError("service autonomy requires the default managed roots")
    verification_argv = (
        json.loads(arguments.verification_argv) if arguments.verification_argv is not None else None
    )
    audit_argv = json.loads(arguments.audit_argv) if arguments.audit_argv is not None else None
    run_id, writer_id = f"run-{uuid.uuid4()}", f"writer-{uuid.uuid4()}"
    state = initial_state(
        workspace, requirements, acceptance, scope, run_id, writer_id, arguments.risk_flag,
    )
    state["revision"] = -1
    state = arm(
        state, requirements, acceptance, arguments.runtime, arguments.service_runner,
        verification_argv, audit_argv,
    )
    lease = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "acquire",
         "--root", arguments.lease_root, "--repo", state["repo_id"], "--workspace", state["workspace"],
         "--task-key", state["task_key"], "--run-id", run_id, "--writer-id", writer_id],
        text=True, capture_output=True, check=False,
    )
    if lease.returncode:
        raise ValueError(lease.stdout.strip() or lease.stderr.strip() or "could not acquire autonomy lease")
    try:
        write = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("delivery_state.py")), "write", "--input", "-",
             "--lease-root", arguments.lease_root, "--state-root", arguments.state_root,
             "--repo-id", state["repo_id"], "--task-key", state["task_key"], "--run-id", run_id,
             "--writer-id", writer_id, "--expected-revision", "-1"],
            input=json.dumps(state), text=True, capture_output=True, check=False,
        )
        if write.returncode:
            raise ValueError(write.stderr.strip() or "could not create autonomy state")
    except Exception as error:
        try:
            _release_lease(arguments, state)
        except (OSError, ValueError, json.JSONDecodeError) as cleanup_error:
            raise ValueError(f"{error}; lease cleanup failed: {cleanup_error}") from error
        raise
    path = state_path(arguments.state_root, state["repo_id"], state["task_key"], run_id)
    return {"status": "armed", "state_path": str(path), "run_id": run_id, "task_key": state["task_key"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--requirement", action="append", default=[])
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--runtime", choices=("hook", "service"), default="hook")
    parser.add_argument("--service-runner", choices=("codex-exec-v1", "claude-code-v1"))
    parser.add_argument("--verification-argv")
    parser.add_argument("--audit-argv")
    parser.add_argument("--risk-flag", action="append", default=[])
    parser.add_argument("--state-root", default=str(Path.home() / ".convergent-delivery" / "state"))
    parser.add_argument("--lease-root", default=str(Path.home() / ".convergent-delivery" / "leases"))
    arguments = parser.parse_args()
    try:
        print(json.dumps(run(arguments), sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"autonomy begin blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
