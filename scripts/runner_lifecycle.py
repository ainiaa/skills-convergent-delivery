#!/usr/bin/env python3
"""Persist and execute one explicit multi-model external runner lifecycle."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import delivery_state
from delivery_next import upgrade_state
from runner_launch import execute_dispatch_launch, plan_dispatch_launch


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
    receipt = execution["receipt"]
    revision = append(_arguments(arguments, revision), "runner_results", receipt)
    return {
        "status": receipt["status"], "launch": launch, "result": receipt,
        "output": execution["output"], "revision": revision,
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
    arguments = parser.parse_args()
    try:
        result = run_dispatch(arguments, json.load(arguments.dispatch), arguments.input.read())
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
