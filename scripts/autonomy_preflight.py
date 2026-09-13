#!/usr/bin/env python3
"""Check only locally observable prerequisites for an explicit Stop-hook install."""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


MIN_CLAUDE_STOP_HOOK_VERSION = (2, 1, 246)


def claude_stop_hook_available(host):
    try:
        result = subprocess.run(
            [host, "--version"], text=True, capture_output=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
    return result.returncode == 0 and match is not None and tuple(
        int(part) for part in match.groups()
    ) >= MIN_CLAUDE_STOP_HOOK_VERSION


def hook_config_path(host):
    home = Path.home()
    if host == "codex":
        return home / ".codex" / "hooks.json"
    return home / ".claude" / "settings.json"


def registered_commands(path, event):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(value, dict):
        return []
    hooks = value.get("hooks")
    entries = hooks.get(event) if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        return []
    commands = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for item in entry.get("hooks", []):
            if isinstance(item, dict) and isinstance(item.get("command"), str):
                commands.append(item["command"])
    return commands


def hook_registered(host, config, expect_stop=None, expect_prompt=None):
    stop = registered_commands(config, "Stop")
    if expect_stop is not None:
        if expect_stop not in stop:
            return False
    elif not any("autonomy_hook.py" in command and f"--host {host}" in command for command in stop):
        return False
    if host == "codex":
        prompt = registered_commands(config, "UserPromptSubmit")
        if expect_prompt is not None:
            if expect_prompt not in prompt:
                return False
        elif not any(
            "autonomy_prompt_hook.py" in command and "--host codex" in command
            for command in prompt
        ):
            return False
    return True


def inspect(host, source, verify_registration=False, config=None, expect_stop=None, expect_prompt=None):
    source = Path(source).expanduser().resolve()
    adapter = source / "scripts" / "autonomy_hook.py"
    host_command = shutil.which(host) is not None
    adapter_works = False
    if adapter.is_file():
        try:
            result = subprocess.run(
                [sys.executable, str(adapter), "--host", host], input="{}", text=True,
                capture_output=True, check=False, timeout=10,
            )
            adapter_works = result.returncode == 0 and json.loads(result.stdout) == {"decision": "approve"}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    if host == "codex":
        checks = {"adapter": adapter_works, "host_command": host_command}
    else:
        checks = {
            "adapter": adapter_works,
            "host_command": host_command,
            "stop_hook": host_command and claude_stop_hook_available(host),
        }
    if verify_registration:
        checks["hook_registered"] = hook_registered(
            host, config or hook_config_path(host), expect_stop, expect_prompt,
        )
    return {"host": host, "supported": all(checks.values()), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude"), required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument(
        "--verify-registration", action="store_true",
        help="also verify the autonomy hooks are registered in the host configuration",
    )
    parser.add_argument(
        "--config", default=None,
        help="override the host hook configuration path checked by --verify-registration",
    )
    parser.add_argument(
        "--expect-stop", default=None,
        help="require this exact Stop hook command instead of a substring match",
    )
    parser.add_argument(
        "--expect-prompt", default=None,
        help="require this exact UserPromptSubmit hook command instead of a substring match",
    )
    arguments = parser.parse_args()
    report = inspect(
        arguments.host, arguments.source, arguments.verify_registration, arguments.config,
        arguments.expect_stop, arguments.expect_prompt,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["supported"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
