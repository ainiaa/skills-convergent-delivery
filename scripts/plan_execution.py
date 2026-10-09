#!/usr/bin/env python3
"""Choose implementation next actions without treating observation gaps as revoked authorization."""

import argparse
import json
import sys
from pathlib import Path, PurePosixPath

from run_contract import action


TOOLING_FAILURE_MARKERS = (
    "closure path has no indexed files",
    "CodeGraph requires a fresh index and verified graph bindings",
    "CodeGraph query failed or timed out",
    "planned graph receipt is unavailable",
)

ACCEPTANCE_TOOL_FAILURES = (
    "native acceptance tool timed out",
    "native acceptance tool is unavailable",
)


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def classify_validation_failure(reason):
    """Keep known observation gaps separate from invalid plans and safety gates."""
    reason = _string(reason, "validation failure")
    if reason in ACCEPTANCE_TOOL_FAILURES or any(marker in reason for marker in TOOLING_FAILURE_MARKERS):
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


def select_task(tasks, statuses, *, global_block=None, budget_exhausted=False):
    """Select one task from validated outcomes; never equate a tooling gap with completion."""
    if not isinstance(tasks, list) or not tasks or len(tasks) > 256 or not isinstance(statuses, dict):
        raise ValueError("tasks and statuses are invalid")
    ids, dependencies, paths = [], {}, {}
    for task in tasks:
        task_id = _string(task.get("task_id"), "task_id") if isinstance(task, dict) else None
        if task_id is None or task_id in ids:
            raise ValueError("task ids must be unique")
        deps, owned = task.get("depends_on"), task.get("owned_paths")
        if not isinstance(deps, list) or any(not isinstance(x, str) or not x for x in deps) \
                or len(deps) != len(set(deps)) or not isinstance(owned, list) or not owned:
            raise ValueError("dependencies or owned_paths are invalid")
        for path in owned:
            if not isinstance(path, str) or not path or PurePosixPath(path).is_absolute() \
                    or ".." in PurePosixPath(path).parts or "\\" in path:
                raise ValueError("owned_paths must be relative paths")
        ids.append(task_id)
        dependencies[task_id], paths[task_id] = set(deps), owned
    if set(statuses) - set(ids) or any(not isinstance(value, str) or value not in {"pending", "running", "completed", "blocked"}
                                     for value in statuses.values()):
        raise ValueError("task statuses are invalid")
    for task_id in ids:
        if dependencies[task_id] - set(ids) or task_id in dependencies[task_id]:
            raise ValueError("unknown or self dependency")
    visited, dependency_order = set(), []
    while len(visited) < len(ids):
        ready = [task_id for task_id in ids if task_id not in visited and dependencies[task_id] <= visited]
        if not ready:
            raise ValueError("task dependencies contain a cycle")
        dependency_order.extend(ready)
        visited.update(ready)
    def overlaps(left, right):
        return any(PurePosixPath(a) == PurePosixPath(b) or PurePosixPath(a) in PurePosixPath(b).parents
                   or PurePosixPath(b) in PurePosixPath(a).parents for a in paths[left] for b in paths[right])

    for index, task_id in enumerate(dependency_order):
        for earlier in dependency_order[:index]:
            if overlaps(earlier, task_id):
                dependencies[task_id].add(earlier)
    visited = set()
    while len(visited) < len(ids):
        ready = {task_id for task_id in ids if task_id not in visited and dependencies[task_id] <= visited}
        if not ready:
            raise ValueError("task dependencies contain a cycle")
        visited.update(ready)
    completed = {task_id for task_id in ids if statuses.get(task_id) == "completed"}
    if any(not dependencies[task_id] <= completed for task_id in completed):
        raise ValueError("completed task has incomplete dependencies")
    blocked = [task_id for task_id in ids if statuses.get(task_id) == "blocked"]
    blocked_overlap = {task_id for task_id in ids if any(overlaps(task_id, other) for other in blocked)}
    waiting = [task_id for task_id in ids if statuses.get(task_id, "pending") == "pending"
               and (not dependencies[task_id] <= completed or task_id in blocked_overlap)]
    result = {"status": "blocked", "task_id": None, "blocked": blocked, "waiting": waiting,
              "reason": global_block or ("budget exhausted" if budget_exhausted else "no independently executable task")}
    if global_block is not None:
        _string(global_block, "global_block")
    if type(budget_exhausted) is not bool:
        raise ValueError("budget_exhausted must be boolean")
    if global_block or budget_exhausted:
        return result
    running = [task_id for task_id in ids if statuses.get(task_id) == "running"]
    if len(running) > 1 or any(not dependencies[task_id] <= completed or task_id in blocked_overlap for task_id in running):
        raise ValueError("running task dependencies or single writer are invalid")
    if running:
        return {**result, "status": "running", "task_id": running[0], "reason": None}
    for task_id in ids:
        if statuses.get(task_id, "pending") == "pending" and task_id not in waiting:
            return {**result, "status": "ready", "task_id": task_id, "reason": None}
    if len(completed) == len(ids):
        return {**result, "status": "verify", "reason": None}
    return result


FINAL_TOOLING_BLOCK = 'final acceptance tooling remains uncovered; no independent task remains'


def tooling_acceptance_recovered(previous, history, current, source):
    """Permit completion only: preserve frozen criteria and require every current proof."""
    from evidence_contract import valid_evidence_receipts
    if not isinstance(source, dict):
        return False

    def receipts(entry):
        if 'evidence_receipts' in entry:
            return entry['evidence_receipts']
        return [entry['evidence']] if isinstance(entry.get('evidence'), dict) else []

    if [entry['criterion'] for entry in previous] != [entry['criterion'] for entry in current]:
        return False
    passed = []
    for entry in current:
        observed = receipts(entry)
        if entry['result'] != 'pass' or entry['freshness'] != 'fresh' \
                or entry.get('source_fingerprint', source['source_fingerprint']) != source['source_fingerprint'] \
                or not valid_evidence_receipts(observed, source):
            return False
        passed.extend(observed)
    gaps = []
    for entry in [*previous, *history]:
        for observed in receipts(entry):
            failure = is_actual_verification_failure(observed)
            if observed['exit_code'] != 0:
                if failure and (entry in previous or not any(proof['argv'] == observed['argv'] for proof in passed)):
                    return False
                if not failure:
                    gaps.append(observed)
    return bool(gaps) and all(any(proof['argv'] == gap['argv'] for proof in passed) for gap in gaps)


def next_plan_action(envelope, workspace, *, implementation_authorized, global_block=None):
    """Audit real task evidence before choosing ordinary same-session plan work."""
    from delivery_next import plan_check_module
    from evidence_contract import validate_observed_evidence_receipt, valid_evidence_receipts

    if type(implementation_authorized) is not bool:
        raise ValueError("implementation_authorized must be boolean")
    if not implementation_authorized or global_block:
        return {"status": "blocked", "reason": global_block or "implementation_authorization_required"}
    audit = plan_check_module().audit(envelope, workspace)
    if audit["scope_drift"] or any(audit["task_scope_drift"].values()) or not audit["source_chain_complete"] \
            or not audit['task_order_valid']:
        return {"status": "blocked", "reason": "plan source boundary, scope or dependency order is not verified"}
    try:
        runtime = require_plan_cleanup(envelope, workspace, audit['source'], final_complete=audit['complete'])
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {'status':'blocked','reason':str(error)}
    final_tooling_gap = False
    current_final = [entry['evidence'] for entry in envelope['final_acceptance']
                     if isinstance(entry, dict) and isinstance(entry.get('evidence'), dict)]
    acceptance_records = [*runtime['ledger']['acceptance'],
                          *(item['acceptance'] for item in runtime['ledger'].get('acceptance_history', []))]
    recorded_final = [receipt for entry in acceptance_records for receipt in entry.get('evidence_receipts', [])]
    recorded_fingerprints = {receipt.get('receipt_fingerprint') for receipt in recorded_final if isinstance(receipt, dict)}
    resolved_tools = {tuple(entry['evidence']['argv']) for entry in envelope['final_acceptance']
                      if entry['result'] in {'unknown', 'pass'} and entry['freshness'] == 'fresh'
                      and entry.get('source_fingerprint', audit['source']['source_fingerprint']) == audit['source']['source_fingerprint']
                      and valid_evidence_receipts([entry.get('evidence')], audit['source'])}
    for observation in [*current_final, *recorded_final]:
        if isinstance(observation, dict):
            failure = is_actual_verification_failure(observation)
            if observation in current_final and not failure and observation['exit_code'] != 0 \
                    and observation['receipt_fingerprint'] not in recorded_fingerprints:
                return {'status':'blocked','reason':'persist final tooling evidence in the managed acceptance ledger before continuing'}
            final_tooling_gap |= not failure and observation['exit_code'] != 0 and tuple(observation['argv']) not in resolved_tools
            if failure and (observation in current_final or tuple(observation['argv']) not in resolved_tools):
                return {'status':'blocked','reason':'actual final verification failure requires resolution'}
    statuses, blockers, recoveries = {}, {}, set()
    persisted_done = {}
    for attempt in runtime['execution_control'].get('autonomy', {}).get('action_attempts', []):
        recorded = attempt['action']
        if recorded.get('phase') in {'implementation', 'implementation-recovery'} \
                and recorded.get('task_id') in {task['task_id'] for task in envelope['plan']['tasks']}:
            try:
                select_task(envelope['plan']['tasks'], {**persisted_done, recorded['task_id']:'running'})
            except ValueError:
                return {'status':'blocked','reason':'persisted implementation dependency order is invalid'}
            result = envelope['task_results'].get(recorded['task_id'], {})
            if attempt['observation']['outcome'] == 'completed' and audit['tasks'][recorded['task_id']] == 'DONE' \
                    and (result.get('prior_attempt') is None or recorded['phase'] == 'implementation-recovery'):
                persisted_done[recorded['task_id']] = 'completed'
        if attempt['observation']['outcome'] == 'unknown':
            return {'status':'blocked','reason':'persisted action outcome is unknown'}
        if recorded.get('action') == 'execute-inline' and recorded.get('task_id') in \
                {task['task_id'] for task in envelope['plan']['tasks']} \
                and recorded['task_id'] not in envelope['task_results']:
            return {'status':'blocked','reason':'persisted implementation history is missing from task results'}
        if recorded.get('phase') in {'implementation', 'implementation-recovery'} \
                and recorded.get('task_id') in envelope['task_results'] and attempt['observation']['outcome'] == 'failed':
            result = envelope['task_results'][recorded['task_id']]
            preserved = []
            for part in (result, result.get('prior_attempt')):
                if isinstance(part, dict):
                    preserved.extend(part.get('evidence', []))
                    blocked_evidence = part.get('blocker', {}).get('evidence')
                    if blocked_evidence is not None:
                        preserved.append(blocked_evidence)
            if not any(isinstance(item, dict) and item.get('receipt_fingerprint') == attempt['observation']['receipt_fingerprint']
                       for item in preserved):
                return {'status':'blocked','reason':'persisted failed implementation receipt is missing from task history'}
        if recorded.get('phase') == 'implementation-recovery':
            result = envelope['task_results'].get(recorded['task_id'], {})
            if result.get('prior_attempt') is None or result.get('recovery_evidence') is None:
                return {'status':'blocked','reason':'persisted recovery history is missing from task results'}
    for task in envelope["plan"]["tasks"]:
        task_id = task["task_id"]
        result = envelope["task_results"].get(task_id)
        if result is None:
            continue
        for attempt in (result.get('prior_attempt'), result):
            if not isinstance(attempt, dict):
                continue
            for observation in attempt.get('evidence', []):
                validate_observed_evidence_receipt(observation)
                if observation['exit_code'] != 0 and observation != attempt.get('blocker', {}).get('evidence'):
                    return {'status':'blocked','reason':f'{task_id}: actual verification failure cannot be locally skipped'}
        if audit["tasks"][task_id] == "DONE":
            statuses[task_id] = "completed"
            if result.get("blocker") is not None:
                require_tool_recovery(result["blocker"], result.get("recovery_evidence"), result.get("source_before"))
            continue
        blocker = result.get("blocker")
        if audit["tasks"][task_id] not in {"PARTIAL", "NOT_DONE"} or not isinstance(blocker, dict) \
                or set(blocker) != {"reason", "evidence"} or blocker["reason"] not in ACCEPTANCE_TOOL_FAILURES:
            return {"status": "blocked", "reason": f"{task_id}: unclassified or non-tooling task failure"}
        require_tool_failure(blocker["reason"], blocker["evidence"])
        attempt = result.get('prior_attempt', result)
        boundary = attempt.get("source_after", blocker['evidence']['source'])
        if blocker["evidence"]["source"] != boundary or boundary not in audit['source_boundaries']:
            raise ValueError("tooling blocker requires observed failure at the task source boundary")
        if result.get("recovery_evidence") is not None:
            if result.get('prior_attempt') is None:
                raise ValueError('recovery requires preserved original attempt history')
            if result["status"] != "NOT_DONE":
                return {"status": "blocked", "reason": f"{task_id}: recovered task failed; recovery budget exhausted"}
            require_tool_recovery(blocker, result["recovery_evidence"], audit["source"])
            autonomy = runtime['execution_control'].get('autonomy')
            if autonomy is None:
                return {'status':'blocked','reason':f'{task_id}: recovery requires persisted action attempts'}
            if any(attempt['action'] == action('execute-inline', task_id=task_id, phase='implementation-recovery')
                   for attempt in autonomy['action_attempts']):
                return {'status':'blocked','reason':f'{task_id}: recovery budget exhausted; record the executed result'}
            recoveries.add(task_id)
            statuses[task_id] = "pending"
            continue
        statuses[task_id], blockers[task_id] = "blocked", blocker["reason"]
    progress = select_task(envelope["plan"]["tasks"], statuses)
    progress["blocker_reasons"] = blockers
    if progress["status"] == "ready":
        return {"status": "execute", "next_action": action("execute-inline", task_id=progress["task_id"],
                                                              phase="implementation-recovery" if progress['task_id'] in recoveries
                                                              else "implementation"), "progress": progress}
    if progress["status"] == "verify":
        if final_tooling_gap:
            return {'status':'blocked','reason':'final acceptance tooling remains uncovered; no independent task remains',
                    'progress':progress}
        task_id = envelope["plan"]["plan_id"]
        return {"status": "complete" if audit["complete"] else "verify",
                "next_action": action("complete", task_id=task_id) if audit["complete"] else
                action("verify", task_id=task_id, target="final-acceptance"), "progress": progress}
    return {"status": "blocked", "reason": progress["reason"], "progress": progress}


def require_tool_recovery(blocker, evidence, source):
    """A recovery observation must run the same tool successfully at the current source boundary."""
    from evidence_contract import validate_observed_evidence_receipt

    if not isinstance(blocker, dict) or blocker.get("reason") not in ACCEPTANCE_TOOL_FAILURES:
        raise ValueError("only a classified tooling blocker may recover")
    require_tool_failure(blocker['reason'], blocker.get("evidence"))
    validate_observed_evidence_receipt(evidence)
    if blocker["evidence"]["exit_code"] == 0 or evidence["exit_code"] != 0 \
            or evidence["argv"] != blocker["evidence"]["argv"] or evidence["source"] != source:
        raise ValueError("recovery requires the same tool's fresh observed pass")


def require_tool_failure(reason, evidence):
    """Only the evidence executor can classify timeout or missing executable."""
    from evidence_contract import validate_observed_evidence_receipt
    validate_observed_evidence_receipt(evidence)
    expected = dict(zip(ACCEPTANCE_TOOL_FAILURES, ('timed_out', 'unavailable')))
    check = evidence.get('test_check', {})
    if reason not in expected or evidence.get('tooling_failure') != expected[reason] \
            or any(check.get(key, 0) for key in ('failed', 'errors', 'xpassed')):
        raise ValueError('local block requires observed tooling timeout or unavailability, without test failures')


def is_actual_verification_failure(evidence):
    from evidence_contract import validate_observed_evidence_receipt
    validate_observed_evidence_receipt(evidence)
    if evidence['exit_code'] == 0:
        return False
    for reason in ACCEPTANCE_TOOL_FAILURES:
        try:
            require_tool_failure(reason, evidence)
            return False
        except ValueError:
            pass
    return True


def require_plan_cleanup(envelope, workspace, source, *, final_complete=False):
    """Read the existing owner state and lease; never infer cleanup from a tooling receipt."""
    from types import SimpleNamespace
    from delivery_next import validate_state, validate_active_lease
    from delivery_state import state_path, project_state_root, project_lease_root
    from runtime_adapter import validate_cleanup_barrier
    from runner_contract import runner_results_complete
    path = Path(_string(envelope.get('runtime_state_path'), 'runtime_state_path')).expanduser().resolve()
    runtime = json.loads(path.read_text(encoding='utf-8'))
    state_root = project_state_root(workspace)
    if path != state_path(state_root, runtime['repo_id'], runtime['task_key'], runtime['run_id']) \
            or Path(runtime['repo_id']).resolve() != state_root.parent.parent \
            or runtime['task_key'] != envelope['plan']['plan_id'] or runtime['workspace'] != str(Path(workspace).resolve()) \
            or runtime.get('source_receipt') != source:
        raise ValueError('plan runtime must be the exact current managed owner state')
    validate_state(runtime, SimpleNamespace(), check_workspace=True)
    validate_active_lease(runtime, SimpleNamespace(lease_root=project_lease_root(workspace),
                          run_id=runtime['run_id'], writer_id=runtime['writer_id']))
    final_recovered = final_complete and runtime.get('blocked_code') == 'environment' \
        and runtime.get('blocked_reason') == FINAL_TOOLING_BLOCK \
        and tooling_acceptance_recovered(runtime['ledger']['acceptance'],
            [item['acceptance'] for item in runtime['ledger'].get('acceptance_history', [])],
            envelope['final_acceptance'], source)
    if runtime['status'] == 'blocked' and not final_recovered \
            or any(worker['status'] == 'working' for worker in runtime['workers']):
        raise ValueError('plan runtime is globally blocked or requires worker cleanup')
    tree = runtime.get('worker_tree_receipt')
    if runtime['workers'] or tree is not None:
        validate_cleanup_barrier(tree, runtime['revision'], {worker['ref'] for worker in runtime['workers']})
    ledger = runtime['ledger']
    if ledger.get('runner_launches') and not runner_results_complete(ledger['runner_launches'], ledger.get('runner_results', [])):
        raise ValueError('plan runtime requires confirmed runner cleanup')
    attempts = runtime['execution_control'].get('autonomy', {}).get('action_attempts', [])
    if any(attempt['status'] != 'committed' for attempt in attempts):
        raise ValueError('plan runtime has an unfinished action attempt')
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id")
    parser.add_argument("--input")
    parser.add_argument("--workspace")
    parser.add_argument("--global-block")
    parser.add_argument("--implementation-authorized", action="store_true")
    observation = parser.add_mutually_exclusive_group()
    observation.add_argument("--validation-error")
    observation.add_argument("--native-preflight-workspace")
    arguments = parser.parse_args()
    if arguments.input is not None:
        if arguments.input != "-" or not arguments.workspace or arguments.task_id \
                or arguments.validation_error or arguments.native_preflight_workspace:
            parser.error("plan selection requires --input - and --workspace, without task preflight arguments")
        try:
            output = next_plan_action(json.load(sys.stdin), arguments.workspace,
                                      implementation_authorized=arguments.implementation_authorized,
                                      global_block=arguments.global_block)
        except (ValueError, OSError, KeyError, TypeError) as error:
            output = {"status": "blocked", "reason": str(error)}
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return
    if not arguments.task_id or arguments.workspace or arguments.global_block:
        parser.error("single task selection requires --task-id")
    validation = (
        classify_validation_failure(arguments.validation_error)
        if arguments.validation_error is not None else {"status": "valid"}
    )
    if arguments.native_preflight_workspace is not None:
        from tdd_impact_guard import preflight

        observed = preflight(arguments.native_preflight_workspace)
        if observed["status"] == "uncovered":
            validation = {"status": "uncovered", "kind": "tooling",
                          "reason": "native preflight uncovered: " + ", ".join(observed["uncovered"])}
    print(json.dumps(decide(
        arguments.task_id,
        implementation_authorized=arguments.implementation_authorized,
        validation=validation,
    ), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
