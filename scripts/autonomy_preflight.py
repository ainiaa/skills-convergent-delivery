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


def inspect(host, source):
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
        try:
            queue_available = host_command and subprocess.run(
                [host, "queue", "--help"], text=True, capture_output=True, check=False, timeout=10,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            queue_available = False
        checks = {"adapter": adapter_works, "host_command": host_command, "queue": queue_available}
    else:
        checks = {
            "adapter": adapter_works,
            "host_command": host_command,
            "stop_hook": host_command and claude_stop_hook_available(host),
        }
    return {"host": host, "supported": all(checks.values()), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude"), required=True)
    parser.add_argument("--source", required=True)
    arguments = parser.parse_args()
    report = inspect(arguments.host, arguments.source)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["supported"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
