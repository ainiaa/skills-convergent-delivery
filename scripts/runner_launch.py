#!/usr/bin/env python3
"""Freeze and execute the one runner selected by an external-runner dispatch."""

import argparse
import json
from pathlib import Path

from claude_exec_runner import command_for_launch as claude_command_for_launch
from claude_exec_runner import execute_launch as execute_claude_launch
from claude_exec_runner import plan_launch as plan_claude_launch
from codex_exec_runner import command_for_launch as codex_command_for_launch
from codex_exec_runner import execute_launch as execute_codex_launch
from codex_exec_runner import plan_launch as plan_codex_launch
from openai_compatible_runner import PROVIDERS, execute_request, plan_request
from runner_contract import validate_launch
from runner_registry import validate_runner_profile


DISPATCH_FIELDS = {
    "status", "role", "mode", "reason", "profile", "profile_fingerprint", "runner_id", "executor",
}


def _profile(dispatch):
    if not isinstance(dispatch, dict) or set(dispatch) != DISPATCH_FIELDS \
            or dispatch.get("status") != "next" or dispatch.get("mode") != "agent" \
            or dispatch.get("executor") != "external_runner":
        raise ValueError("external runner dispatch is invalid")
    profile = validate_runner_profile(dispatch["profile"])
    if dispatch.get("runner_id") != profile["runner_id"] \
            or dispatch.get("profile_fingerprint") != profile["profile_fingerprint"]:
        raise ValueError("external runner dispatch profile fingerprint is invalid")
    return profile


def plan_dispatch_launch(dispatch, prompt, *, workspace, codex_bin="codex", claude_bin="claude"):
    """Turn exactly one frozen external-runner dispatch into a prompt-free launch receipt."""
    profile = _profile(dispatch)
    if profile["runner_id"] == "codex-exec-v1":
        return plan_codex_launch(profile, prompt, workspace=workspace, codex_bin=codex_bin)
    if profile["runner_id"] == "claude-code-v1":
        return plan_claude_launch(profile, prompt, workspace=workspace, claude_bin=claude_bin)
    provider = PROVIDERS.get(profile["effective"]["provider"])
    if profile["runner_id"] != "openai-compatible-v1" or provider is None:
        raise ValueError("external runner dispatch selects an unsupported runner")
    effort_binding = provider["effort_bindings"].get(profile["effective"]["reasoning_effort"])
    if effort_binding is None:
        raise ValueError("external runner dispatch has no approved effort binding")
    return plan_request(
        profile, prompt, base_url=provider["origin"] + "/api/paas/v4",
        api_key_env=provider["api_key_env"], effort_binding=effort_binding,
    )


def command_for_dispatch(launch, prompt):
    launch = validate_launch(launch, prompt)
    if launch["runner_id"] == "codex-exec-v1":
        return codex_command_for_launch(launch, prompt)
    if launch["runner_id"] == "claude-code-v1":
        return claude_command_for_launch(launch, prompt)
    raise ValueError("external runner launch does not produce a local command")


def execute_dispatch_launch(launch, prompt, *, allow_execute=False, allow_network=False):
    """Execute only the frozen launch after the caller explicitly authorizes its transport."""
    launch = validate_launch(launch, prompt)
    if launch["runner_id"] == "codex-exec-v1":
        receipt, content = execute_codex_launch(
            launch, prompt, allow_execute=allow_execute, capture_content=True,
        )
        return {"receipt": receipt, "output": _output(content)}
    if launch["runner_id"] == "claude-code-v1":
        receipt, content = execute_claude_launch(
            launch, prompt, allow_execute=allow_execute, capture_content=True,
        )
        return {"receipt": receipt, "output": _output(content)}
    if launch["runner_id"] == "openai-compatible-v1":
        result = execute_request(
            launch, prompt, allow_network=allow_network, capture_content=True,
        )
        if isinstance(result, tuple):
            receipt, content = result
            return {"receipt": receipt, "output": _output(content)}
        return {"receipt": result, "output": _output(None)}
    raise ValueError("external runner launch selects an unsupported runner")


def _output(content):
    if isinstance(content, str) and content.strip():
        return {"status": "available", "content": content}
    return {"status": "unavailable"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--dispatch", type=argparse.FileType("r"), required=True)
    plan.add_argument("--input", type=argparse.FileType("r"), required=True)
    plan.add_argument("--workspace", type=Path, required=True)
    plan.add_argument("--codex-bin", default="codex")
    plan.add_argument("--claude-bin", default="claude")
    command = subparsers.add_parser("command")
    command.add_argument("--launch", type=argparse.FileType("r"), required=True)
    command.add_argument("--input", type=argparse.FileType("r"), required=True)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--launch", type=argparse.FileType("r"), required=True)
    execute.add_argument("--input", type=argparse.FileType("r"), required=True)
    execute.add_argument("--allow-execute", action="store_true")
    execute.add_argument("--allow-network", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.command == "plan":
            result = plan_dispatch_launch(
                json.load(arguments.dispatch), arguments.input.read(), workspace=arguments.workspace,
                codex_bin=arguments.codex_bin, claude_bin=arguments.claude_bin,
            )
        elif arguments.command == "command":
            result = command_for_dispatch(json.load(arguments.launch), arguments.input.read())
        else:
            result = execute_dispatch_launch(
                json.load(arguments.launch), arguments.input.read(),
                allow_execute=arguments.allow_execute, allow_network=arguments.allow_network,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
