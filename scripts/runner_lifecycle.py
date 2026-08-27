#!/usr/bin/env python3
"""Persist and execute one explicit multi-model external runner lifecycle."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import delivery_state
from delivery_next import upgrade_state
from role_result import result_from_output
from runner_launch import execute_dispatch_launch, plan_dispatch_launch, prompt_for_dispatch
from runner_contract import bind_role_result
from role_fanout import fan_in, tasks_for_fanout


def _arguments(arguments, revision):
    return SimpleNamespace(**{**vars(arguments), "expected_revision": revision, "strict_evidence": True})


def load_current(arguments):
    path = delivery_state.state_path(
        delivery_state.DEFAULT_STATE_ROOT, arguments.repo_id, arguments.task_key, arguments.run_id,
    )
    if not path.is_file():
        raise ValueError("runner lifecycle requires an existing managed state")
    state = upgrade_state(json.loads(path.read_text(encoding="utf-8")))
    delivery_state.validate_candidate(state, _arguments(arguments, state["revision"]))
    if state["revision"] != arguments.expected_revision:
        raise ValueError("expected revision does not match current state")
    return state


def run_dispatch(arguments, dispatch, prompt, *, load=load_current,
                 append=delivery_state.append_runner_record, execute=execute_dispatch_launch):
    """Persist launch before the side effect; never retry a persisted unknown launch."""
    if arguments.allow_execute is not True:
        raise ValueError("runner lifecycle requires explicit --allow-execute")
    state = load(arguments)
    prompt = prompt_for_dispatch(dispatch, prompt)
    launch = plan_dispatch_launch(
        dispatch, prompt, workspace=state["workspace"], codex_bin=arguments.codex_bin,
        claude_bin=arguments.claude_bin,
    )
    if launch["runner_id"] == "openai-compatible-v1" and arguments.allow_network is not True:
        raise ValueError("external runner lifecycle requires explicit --allow-network")
    revision = append(_arguments(arguments, state["revision"]), "runner_launches", launch)
    execution = execute(
        launch, prompt, allow_execute=True, allow_network=arguments.allow_network,
    )
    if not isinstance(execution, dict) or set(execution) != {"receipt", "output"} \
            or not isinstance(execution["output"], dict):
        raise ValueError("runner execution result is invalid")
    receipt, role_result = _completed_execution(launch, execution)
    revision = append(_arguments(arguments, revision), "runner_results", receipt)
    return {
        "status": receipt["status"], "launch": launch, "result": receipt,
        "role_result": role_result, "revision": revision,
    }


def _completed_execution(launch, execution):
    if not isinstance(execution, dict) or set(execution) != {"receipt", "output"} \
            or not isinstance(execution["output"], dict):
        raise ValueError("runner execution result is invalid")
    receipt = execution["receipt"]
    role_result = result_from_output(launch, execution["output"])
    if receipt.get("status") == "completed" and role_result["role"] in {"scout", "reviewer"}:
        receipt = bind_role_result(launch, receipt, role_result)
    return receipt, role_result


def run_fanout(arguments, dispatch, prompts, *, load=load_current,
               append_launches=delivery_state.append_runner_records,
               append=delivery_state.append_runner_record, execute=execute_dispatch_launch):
    """Persist all bounded read-only launches before concurrently executing and merging them."""
    if arguments.allow_execute is not True:
        raise ValueError("runner lifecycle requires explicit --allow-execute")
    tasks = tasks_for_fanout(dispatch)
    if not isinstance(prompts, dict) or set(prompts) != {task["task_id"] for task in tasks}:
        raise ValueError("fan-out prompts must match the frozen task ids")
    state = load(arguments)
    prepared = []
    for task in tasks:
        prompt = prompt_for_dispatch(task["dispatch"], prompts[task["task_id"]])
        launch = plan_dispatch_launch(
            task["dispatch"], prompt, workspace=state["workspace"], codex_bin=arguments.codex_bin,
            claude_bin=arguments.claude_bin,
        )
        prepared.append({"task_id": task["task_id"], "launch": launch, "prompt": prompt})
    if any(item["launch"]["runner_id"] == "openai-compatible-v1" for item in prepared) \
            and arguments.allow_network is not True:
        raise ValueError("external runner lifecycle requires explicit --allow-network")
    revision = append_launches(
        _arguments(arguments, state["revision"]), "runner_launches",
        [item["launch"] for item in prepared],
    )
    with ThreadPoolExecutor(max_workers=len(prepared)) as executor:
        futures = [
            executor.submit(
                execute, item["launch"], item["prompt"], allow_execute=True,
                allow_network=arguments.allow_network,
            )
            for item in prepared
        ]
        executions = [future.result() for future in futures]
    completed = []
    for item, execution in zip(prepared, executions):
        receipt, role_result = _completed_execution(item["launch"], execution)
        revision = append(_arguments(arguments, revision), "runner_results", receipt)
        completed.append({"task_id": item["task_id"], "role_result": role_result})
    return {
        "status": "completed",
        "fan_in": fan_in(dispatch, completed, {item["task_id"]: item["launch"] for item in prepared}),
        "revision": revision,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch", type=argparse.FileType("r"), required=True)
    parser.add_argument("--input", type=argparse.FileType("r"), required=True)
    parser.add_argument("--lease-root", default=str(Path.home() / ".convergent-delivery" / "leases"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--writer-id", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--allow-execute", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--fanout", action="store_true")
    arguments = parser.parse_args()
    try:
        dispatch = json.load(arguments.dispatch)
        prompt = arguments.input.read()
        result = (
            run_fanout(arguments, dispatch, json.loads(prompt))
            if arguments.fanout else run_dispatch(arguments, dispatch, prompt)
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
