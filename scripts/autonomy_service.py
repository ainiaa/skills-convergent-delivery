#!/usr/bin/env python3
"""Run explicitly armed service-mode autonomy without retaining model transcripts."""

import argparse
import copy
import fcntl
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager

from autonomy_gate import decide
from claude_exec_runner import execute_launch as execute_claude, plan_launch as plan_claude
from codex_exec_runner import execute_launch as execute_codex, plan_launch as plan_codex
from delivery_next import validate_active_lease, validate_native_tdd_trace, validate_state
from delivery_state import DEFAULT_STATE_ROOT, state_path as managed_state_path
from evidence_contract import run_evidence, workspace_source
from tdd_impact_guard import MAX_TRACE_BYTES, MAX_RERUN_TIMEOUT_SECONDS, rerun as rerun_tdd_trace


def service_runtime(state):
    runtime = state.get("execution_control", {}).get("autonomy", {}).get("runtime")
    if not isinstance(runtime, dict) or runtime.get("mode") != "service":
        raise ValueError("state is not armed for the autonomous service")
    return runtime


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _service_lock(state_path):
    """Allow one service controller to advance one managed state at a time."""
    lock_path = state_path.with_name(f".{state_path.name}.service.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _time_policy(profile):
    absolute = profile["budget"]["timeout_seconds"]
    startup = min(30, absolute)
    return {
        "startup_seconds": startup,
        "idle_seconds": min(max(startup, 60), absolute),
        "absolute_seconds": absolute,
        "max_extensions": 0,
    }


def _write(state_path, state, state_root, lease_root):
    command = [
        sys.executable, str(Path(__file__).with_name("delivery_state.py")), "write", "--input", "-",
        "--lease-root", str(lease_root), "--state-root", str(state_root),
        "--repo-id", state["repo_id"], "--task-key", state["task_key"], "--run-id", state["run_id"],
        "--writer-id", state["writer_id"], "--expected-revision", str(state["revision"]),
    ]
    candidate = copy.deepcopy(state)
    candidate["revision"] += 1
    result = subprocess.run(command, input=json.dumps(candidate), text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "autonomy service could not persist state")
    return json.loads(Path(state_path).read_text(encoding="utf-8"))


def _update(state_path, state_root, lease_root, mutate, *, refresh_source=False):
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    mutate(state)
    if refresh_source:
        state["source_receipt"] = workspace_source(state["workspace"], state["baseline"]["commit"])
        state["source_fingerprint"] = state["source_receipt"]["source_fingerprint"]
    rounds = state["execution_control"]["review"]["rounds"]
    if rounds and rounds[-1]["source_fingerprint"] != state["source_fingerprint"]:
        # Preserve earlier reviews; a changed source starts with no review evidence.
        rounds.append({"source_fingerprint": state["source_fingerprint"], "requests": []})
    return _write(state_path, state, state_root, lease_root)


def _attempt(state, action):
    return {
        "attempt_id": "attempt-" + _fingerprint({"action": action, "revision": state["revision"]})[:24],
        "action": action,
        "status": "intent",
        "owner": state["writer_id"],
        "time_policy": _time_policy(service_runtime(state)["runner_profile"]),
        "events": [], "observation": None, "commit": None,
    }


def _latest(state):
    return state["execution_control"]["autonomy"]["action_attempts"][-1]


def _append_intent(state_path, state_root, lease_root, action):
    return _update(
        state_path, state_root, lease_root,
        lambda state: state["execution_control"]["autonomy"]["action_attempts"].append(_attempt(state, action)),
    )


def _start(state_path, state_root, lease_root):
    def mutate(state):
        attempt = _latest(state)
        attempt["status"] = "running"
        attempt["events"].append({
            "kind": "started", "at": _timestamp(),
            "evidence_fingerprint": _fingerprint({"attempt_id": attempt["attempt_id"], "action": attempt["action"]}),
        })
    return _update(state_path, state_root, lease_root, mutate)


def _observe(state_path, state_root, lease_root, receipt):
    outcomes = {"completed": "completed", "failed": "failed", "timed_out": "interrupted",
                "output_exceeded": "interrupted", "unknown": "unknown"}

    def mutate(state):
        attempt = _latest(state)
        attempt["status"] = "observed"
        attempt["events"].append({
            "kind": "terminated", "at": _timestamp(),
            "evidence_fingerprint": receipt["receipt_fingerprint"],
        })
        attempt["observation"] = {
            "outcome": outcomes.get(receipt["status"], "unknown"),
            "receipt_fingerprint": receipt["receipt_fingerprint"],
        }
    return _update(state_path, state_root, lease_root, mutate, refresh_source=True)


def _commit(state_path, state_root, lease_root, verification):
    def mutate(state):
        attempt = _latest(state)
        attempt["status"] = "committed"
        attempt["commit"] = {
            "source_fingerprint": state["source_fingerprint"],
            "verification_fingerprint": verification["receipt_fingerprint"],
        }
    return _update(state_path, state_root, lease_root, mutate)


def _advance_verified_action(state_path, state_root, lease_root, action, verification):
    def mutate(state):
        source = verification["source"]
        state["source_receipt"] = source
        state["source_fingerprint"] = source["source_fingerprint"]
        if action["phase"] == "autonomy-repair":
            autonomy = state["execution_control"]["autonomy"]
            if not autonomy["audit_batches"] or autonomy["audit_batches"][-1]["status"] != "findings" \
                    or autonomy["repair_budget_remaining"] != 1:
                raise ValueError("autonomy repair is not authorized by an initial audit finding")
            autonomy["repair_budget_remaining"] = 0
            state["ledger"].setdefault("autonomy_repair_fingerprints", []).append(
                verification["receipt_fingerprint"]
            )
            state["current_stage"] = "verify-final"
        else:
            state["current_stage"] = action["phase"]
    return _update(state_path, state_root, lease_root, mutate)


def _complete(state_path, state_root, lease_root, verification, audit, tdd_trace=None):
    def mutate(state):
        source_receipt = verification["source"]
        source = source_receipt["source_fingerprint"]
        state["source_receipt"] = source_receipt
        state["source_fingerprint"] = source
        state["current_stage"] = "verify-final"
        autonomy = state.get("execution_control", {}).get("autonomy")
        if autonomy is not None:
            attempts = autonomy["action_attempts"]
            if not attempts:
                raise ValueError("autonomous completion requires a committed action")
            attempt = attempts[-1]
            attempt["status"] = "committed"
            attempt["commit"] = {
                "source_fingerprint": source,
                "verification_fingerprint": verification["receipt_fingerprint"],
            }
        if autonomy is not None and not autonomy["audit_batches"]:
            autonomy["audit_batches"].append({
                "source_fingerprint": source,
                "phase": "initial",
                "status": "pass",
                "covered_manifest_ids": [item["id"] for item in autonomy["manifest"]["items"]],
                "finding_fingerprints": [],
                "evidence_receipt_fingerprint": audit["receipt_fingerprint"],
            })
        elif autonomy is not None and len(autonomy["audit_batches"]) == 1 \
                and autonomy["audit_batches"][0]["status"] == "findings" \
                and autonomy["repair_budget_remaining"] == 0 \
                and autonomy["re_audit_budget_remaining"] == 1:
            autonomy["audit_batches"].append({
                "source_fingerprint": source,
                "phase": "re_audit",
                "status": "pass",
                "covered_manifest_ids": [item["id"] for item in autonomy["manifest"]["items"]],
                "finding_fingerprints": [],
                "evidence_receipt_fingerprint": audit["receipt_fingerprint"],
            })
            autonomy["re_audit_budget_remaining"] = 0
        elif autonomy is not None:
            raise ValueError("service final audit is not eligible for completion")
        ledger = state["ledger"]
        if tdd_trace is not None:
            ledger["tdd_trace"] = tdd_trace
            ledger.pop("tdd_trace_candidate", None)
        ledger["checks"].append({
            "stage": "autonomy-audit", "command": audit["command"], "result": "pass",
            "evidence_receipts": [audit],
        })
        history = ledger.setdefault("acceptance_history", [])
        for item in ledger["acceptance"]:
            history.append({"revision": state["revision"], "acceptance": copy.deepcopy(item)})
            item.update(
                evidence=verification["command"], result="pass", freshness="fresh",
                source_fingerprint=source, evidence_receipts=[verification],
            )
        state["status"] = "complete"
    return _update(state_path, state_root, lease_root, mutate)


def _release(state, state_root, lease_root):
    result = subprocess.run([
        sys.executable, str(Path(__file__).with_name("delivery_lease.py")), "release",
        "--root", str(lease_root), "--state-root", str(state_root), "--repo", state["repo_id"],
        "--workspace", state["workspace"], "--task-key", state["task_key"],
        "--run-id", state["run_id"], "--writer-id", state["writer_id"],
    ], capture_output=True, text=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown release failure"
        raise ValueError(f"autonomy lease release failed: {detail}")
    try:
        outcome = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("autonomy lease release returned invalid output") from error
    if outcome != {"status": "released"}:
        raise ValueError("autonomy lease release failed")


def prompt(state_path, next_action):
    return (
        "Execute exactly one frozen Converge autonomous action. Read the managed state at "
        f"{state_path}. The gate selected {json.dumps(next_action, sort_keys=True)}. "
        "Work only within its frozen scope and use current evidence. Do not modify the managed "
        "state: the service controller records the verified source and advances the stage after "
        "this action exits. Do not report completion from prose, publish, or create another agent."
        " For native work, preserve real RED/GREEN observed Evidence Receipts while implementing."
        " Return only JSON {\"tdd_trace\": <TDD/Impact Trace v5>} after code changes and for verify-final."
        " Read the frozen references/tdd-providers.md through the state's controller snapshot."
        " Reuse ledger.tdd_trace_candidate from prior actions, update it for the current source,"
        " and keep original RED receipts; never invent receipts. A scope-only action may return {}."
        " The controller stores this untrusted candidate and reruns it before final completion."
    )


def _append_runner_record(state_path, state_root, lease_root, field, record):
    return _update(
        state_path, state_root, lease_root,
        lambda state: state["ledger"].setdefault(field, []).append(record),
        refresh_source=field == "runner_results",
    )


def execute(state_path, state, next_action, state_root, lease_root):
    runtime = service_runtime(state)
    profile = runtime["runner_profile"]
    request = prompt(state_path, next_action)
    runner = profile["runner_id"]
    if runner == "codex-exec-v1":
        launch = plan_codex(profile, request, workspace=state["workspace"])
        run = execute_codex
    elif runner == "claude-code-v1":
        launch = plan_claude(profile, request, workspace=state["workspace"])
        run = execute_claude
    else:
        raise ValueError("autonomy service runner is unsupported")
    _append_runner_record(state_path, state_root, lease_root, "runner_launches", launch)
    receipt, content = run(launch, request, allow_execute=True, capture_content=True)
    _append_runner_record(state_path, state_root, lease_root, "runner_results", receipt)
    if receipt["status"] == "completed" and content:
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_TRACE_BYTES:
            raise ValueError("service TDD output exceeds the trace size limit")
        try:
            output = json.loads(content)
        except json.JSONDecodeError:
            output = None
        if isinstance(output, dict) and "tdd_trace" in output:
            def store_trace(candidate):
                trace = output["tdd_trace"]
                validate_native_tdd_trace(
                    trace, candidate["source_receipt"],
                    candidate["execution_control"]["routing"]["profile"]["risk_flags"],
                    [item["criterion"] for item in candidate["ledger"]["acceptance"]],
                    required=False, workspace=candidate["workspace"],
                )
                candidate["ledger"]["tdd_trace_candidate"] = trace
            _update(state_path, state_root, lease_root, store_trace)
    return receipt


def block(state_path, state, state_root, lease_root, reason, evidence=None, stage="autonomy-audit"):
    def mutate(candidate):
        candidate.update(status="blocked", blocked_code="no_progress", blocked_reason=reason)
        if evidence is not None:
            candidate["ledger"]["checks"].append({
                "stage": stage, "command": evidence["command"], "result": "fail",
                "evidence_receipts": [evidence],
            })

    blocked = _update(
        state_path, state_root, lease_root,
        mutate, refresh_source=True,
    )
    _release(blocked, state_root, lease_root)
    return blocked


def _record_audit_findings(state_path, state_root, lease_root, verification, audit):
    def mutate(state):
        autonomy = state["execution_control"]["autonomy"]
        if autonomy["audit_batches"] or autonomy["repair_budget_remaining"] != 1:
            raise ValueError("autonomous audit findings cannot be repaired again")
        source = verification["source"]
        state["source_receipt"] = source
        state["source_fingerprint"] = source["source_fingerprint"]
        state["current_stage"] = "autonomy-repair"
        autonomy["audit_batches"].append({
            "source_fingerprint": source["source_fingerprint"],
            "phase": "initial",
            "status": "findings",
            "covered_manifest_ids": [item["id"] for item in autonomy["manifest"]["items"]],
            "finding_fingerprints": [audit["receipt_fingerprint"]],
            "evidence_receipt_fingerprint": audit["receipt_fingerprint"],
        })
        attempt = _latest(state)
        attempt["status"] = "committed"
        attempt["commit"] = {
            "source_fingerprint": source["source_fingerprint"],
            "verification_fingerprint": verification["receipt_fingerprint"],
        }
    return _update(state_path, state_root, lease_root, mutate)


def _finalize_observed(state_path, state_root, lease_root):
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    attempt = _latest(state)
    if attempt["observation"]["outcome"] != "completed":
        block(state_path, state, state_root, lease_root, "autonomous action did not complete")
        return {"status": "blocked", "reason": "runner_not_completed"}
    verification = run_evidence(
        state["workspace"], state["baseline"]["commit"], service_runtime(state)["verification_argv"],
        timeout_seconds=_time_policy(service_runtime(state)["runner_profile"])["absolute_seconds"],
    )
    if verification["exit_code"] != 0:
        block(
            state_path, state, state_root, lease_root, "frozen autonomous verification failed",
            verification, stage="autonomy-verification",
        )
        return {"status": "blocked", "reason": "verification_failed", "verification": verification}
    if attempt["action"].get("phase") == "verify-final":
        audit = run_evidence(
            state["workspace"], state["baseline"]["commit"],
            service_runtime(state)["audit_argv"],
            timeout_seconds=_time_policy(service_runtime(state)["runner_profile"])["absolute_seconds"],
        )
        if audit["source"] != verification["source"]:
            block(state_path, state, state_root, lease_root, "frozen autonomous audit failed", audit)
            return {"status": "blocked", "reason": "audit_failed", "audit": audit}
        findings_code = service_runtime(state).get("audit_findings_exit_code")
        if audit["exit_code"] == findings_code:
            autonomy = state["execution_control"]["autonomy"]
            if autonomy["audit_batches"] or autonomy["repair_budget_remaining"] != 1:
                block(
                    state_path, state, state_root, lease_root,
                    "autonomous audit findings remain after the one permitted repair", audit,
                )
                return {"status": "blocked", "reason": "audit_findings_after_repair", "audit": audit}
            repaired = _record_audit_findings(state_path, state_root, lease_root, verification, audit)
            return {"status": "advanced", "reason": "audit_findings", "audit": audit,
                    "revision": repaired["revision"]}
        if audit["exit_code"] != 0:
            block(state_path, state, state_root, lease_root, "frozen autonomous audit failed", audit)
            return {"status": "blocked", "reason": "audit_failed", "audit": audit}
        trace = None
        if state["provider_binding"]["binding"]["workflow_provider"]["id"] == "native-v1":
            trace = state["ledger"].get("tdd_trace_candidate", state["ledger"].get("tdd_trace"))
            validate_native_tdd_trace(
                trace, verification["source"], state["execution_control"]["routing"]["profile"]["risk_flags"],
                [item["criterion"] for item in state["ledger"]["acceptance"]],
                required=True, workspace=state["workspace"],
            )
            trace = rerun_tdd_trace(
                trace, state["workspace"], state["baseline"]["commit"], native_coverage=True,
                timeout_seconds=min(MAX_RERUN_TIMEOUT_SECONDS,
                                    _time_policy(service_runtime(state)["runner_profile"])["absolute_seconds"]),
            )
        completed = _complete(state_path, state_root, lease_root, verification, audit, trace)
        _release(completed, state_root, lease_root)
        return {"status": "complete", "verification": verification, "audit": audit,
                "revision": completed["revision"]}
    _advance_verified_action(state_path, state_root, lease_root, attempt["action"], verification)
    committed = _commit(state_path, state_root, lease_root, verification)
    return {"status": "advanced", "verification": verification}


def _run_once(state_path, state_root, lease_root):
    state = json.loads(state_path.read_text(encoding="utf-8"))
    attempts = state["execution_control"]["autonomy"]["action_attempts"]
    if attempts and attempts[-1]["status"] == "running":
        # A process may have changed the workspace before a crash; never replay an uncertain action.
        _observe(state_path, state_root, lease_root, {
            "status": "unknown", "receipt_fingerprint": _fingerprint({"attempt_id": _latest(state)["attempt_id"], "lost": True}),
        })
        return _finalize_observed(state_path, state_root, lease_root)
    if attempts and attempts[-1]["status"] == "observed":
        return _finalize_observed(state_path, state_root, lease_root)
    action = decide(state, lease_root=lease_root)
    if action["decision"] == "allow":
        return {"status": "terminal", "terminal": action["terminal"]}
    next_action = action["next_action"]
    executable = next_action["action"] == "execute-inline" or (
        next_action["action"] == "verify" and "phase" in next_action
    )
    if not executable:
        block(
            state_path, state, state_root, lease_root,
            f"autonomous service requires a host controller action: {next_action['action']}",
        )
        return {"status": "blocked", "reason": "host_action_required"}
    if attempts and attempts[-1]["status"] == "intent":
        if _latest(state)["action"] != next_action:
            block(state_path, state, state_root, lease_root, "pending autonomous action no longer matches the gate")
            return {"status": "blocked", "reason": "stale_intent"}
    elif not attempts or attempts[-1]["status"] == "committed":
        _append_intent(state_path, state_root, lease_root, next_action)
    else:
        raise ValueError("autonomous action lifecycle is invalid")
    started = _start(state_path, state_root, lease_root)
    receipt = execute(state_path, started, next_action, state_root, lease_root)
    _observe(state_path, state_root, lease_root, receipt)
    return _finalize_observed(state_path, state_root, lease_root)


def recovering_action(state):
    if not isinstance(state, dict) or state.get("status") != "active":
        return False
    control = state.get("execution_control")
    autonomy = control.get("autonomy") if isinstance(control, dict) else None
    attempts = autonomy.get("action_attempts") if isinstance(autonomy, dict) else None
    return isinstance(attempts, list) and bool(attempts) and isinstance(attempts[-1], dict) \
        and attempts[-1].get("status") in {"running", "observed"}


def run_once(state_path, state_root=DEFAULT_STATE_ROOT, lease_root=None):
    state_path = Path(state_path).expanduser().resolve()
    state_root = Path(state_root).expanduser().resolve()
    lease_root = Path(lease_root or Path.home() / ".convergent-delivery" / "leases").expanduser().resolve()
    with _service_lock(state_path) as acquired:
        if not acquired:
            return {"status": "busy"}
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            validate_state(state, SimpleNamespace(strict_evidence=True),
                           check_workspace=not recovering_action(state))
            if state_path != managed_state_path(
                    state_root, state["repo_id"], state["task_key"], state["run_id"]
            ).resolve():
                raise ValueError("autonomous service state path does not match state root")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise ValueError(
                f"manual recovery required for autonomous service state {state_path}: {error}"
            ) from error
        service_runtime(state)
        if state["status"] in {"complete", "blocked"}:
            _release(state, state_root, lease_root)
            return {"status": "terminal", "terminal": state["status"]}
        validate_active_lease(state, SimpleNamespace(
            lease_root=lease_root, run_id=state["run_id"], writer_id=state["writer_id"],
        ))
        try:
            return _run_once(state_path, state_root, lease_root)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("status") != "active":
                    raise ValueError("state is not an active recoverable service run")
                service_runtime(state)
                block(state_path, state, state_root, lease_root, f"autonomous service error: {error}")
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as recovery_error:
                raise ValueError(
                    f"manual recovery required for autonomous service state {state_path}: {recovery_error}"
                ) from error
            return {"status": "blocked", "reason": str(error)}


def service_paths(root):
    paths, diagnostics = [], []
    for path in sorted(Path(root).expanduser().resolve().rglob("*.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            diagnostics.append(f"unreadable managed state {path}: {error}")
            continue
        if not isinstance(state, dict):
            diagnostics.append(f"invalid autonomous service state {path}: state is not an object")
            continue
        runtime = state.get("execution_control", {}).get("autonomy", {}).get("runtime") \
            if isinstance(state.get("execution_control"), dict) \
            and isinstance(state["execution_control"].get("autonomy"), dict) else None
        if state.get("status") not in {"active", "complete", "blocked"} or not isinstance(runtime, dict) \
                or runtime.get("mode") != "service":
            continue
        try:
            if not has_frozen_snapshot(state):
                validate_state(state, SimpleNamespace(strict_evidence=True),
                               check_workspace=not recovering_action(state))
            service_runtime(state)
        except (KeyError, ValueError) as error:
            diagnostics.append(f"invalid autonomous service state {path}: {error}")
            continue
        paths.append(path)
    return paths, diagnostics


def has_frozen_snapshot(state):
    snapshot = state.get("controller", {}).get("snapshot") if isinstance(state, dict) else None
    return isinstance(snapshot, dict)


def run_frozen_service(state_path, state_root, lease_root, block_reason=None):
    command = [
        sys.executable, str(Path(__file__).with_name("controller_snapshot.py")), "run",
        "--descriptor", str(state_path), "--script", "scripts/autonomy_service.py", "--",
        "--state", str(state_path), "--state-root", str(state_root), "--frozen-runtime",
    ]
    if lease_root:
        command.extend(("--lease-root", str(lease_root)))
    if block_reason:
        command.extend(("--block-reason", block_reason))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "frozen autonomous service failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("frozen autonomous service returned invalid JSON") from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state")
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--lease-root")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--frozen-runtime", action="store_true")
    parser.add_argument("--block-reason")
    arguments = parser.parse_args()
    if bool(arguments.state) == arguments.serve:
        raise ValueError("provide exactly one of --state or --serve")
    if arguments.block_reason and (not arguments.state or not arguments.frozen_runtime):
        raise ValueError("--block-reason requires --state and --frozen-runtime")
    if arguments.serve and arguments.frozen_runtime:
        raise ValueError("--frozen-runtime requires --state")
    if arguments.state:
        try:
            state = json.loads(Path(arguments.state).read_text(encoding="utf-8"))
            if not arguments.frozen_runtime and has_frozen_snapshot(state):
                outcome = run_frozen_service(arguments.state, arguments.state_root, arguments.lease_root)
            elif arguments.block_reason:
                block(
                    Path(arguments.state), state, Path(arguments.state_root),
                    Path(arguments.lease_root or Path.home() / ".convergent-delivery" / "leases"),
                    arguments.block_reason,
                )
                outcome = {"status": "blocked", "reason": arguments.block_reason}
            else:
                outcome = run_once(arguments.state, arguments.state_root, arguments.lease_root)
            print(json.dumps(outcome, sort_keys=True))
            return 0
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            print(f"autonomous service blocked: {error}", file=sys.stderr)
            return 2
    cycles = {}
    reported_diagnostics = set()
    cleaned_terminals = set()
    failed_paths = set()
    while True:
        paths, diagnostics = service_paths(arguments.state_root)
        for diagnostic in diagnostics:
            if diagnostic not in reported_diagnostics:
                print(f"autonomous service blocked: {diagnostic}", file=sys.stderr)
                reported_diagnostics.add(diagnostic)
        if not paths:
            return 0
        active_paths = False
        for path in paths:
            try:
                key = str(path)
                state = json.loads(path.read_text(encoding="utf-8"))
                if state["status"] in {"complete", "blocked"}:
                    if key not in cleaned_terminals:
                        if has_frozen_snapshot(state):
                            run_frozen_service(path, arguments.state_root, arguments.lease_root)
                        else:
                            run_once(path, arguments.state_root, arguments.lease_root)
                        cleaned_terminals.add(key)
                    continue
                if key in failed_paths:
                    continue
                active_paths = True
                limit = service_runtime(state)["max_cycles"]
                if cycles.get(key, 0) >= limit:
                    reason = "autonomous service exhausted its frozen cycle budget"
                    if has_frozen_snapshot(state):
                        run_frozen_service(path, arguments.state_root, arguments.lease_root, reason)
                    else:
                        block(path, state, Path(arguments.state_root), arguments.lease_root or
                              Path.home() / ".convergent-delivery" / "leases", reason)
                    continue
                if has_frozen_snapshot(state):
                    outcome = run_frozen_service(path, arguments.state_root, arguments.lease_root)
                else:
                    outcome = run_once(path, arguments.state_root, arguments.lease_root)
                if outcome["status"] != "busy":
                    cycles[key] = cycles.get(key, 0) + 1
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                print(f"autonomous service blocked: {path}: {error}", file=sys.stderr)
                failed_paths.add(str(path))
        if not active_paths:
            return 0
        time.sleep(5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        raise SystemExit(2)
