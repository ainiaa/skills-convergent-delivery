#!/usr/bin/env python3
"""Install or remove one exact Converge Hook entry without touching peers."""

import argparse
import json
import os
import shlex
import tempfile
from pathlib import Path


HOOK_TIMEOUT_SECONDS = 30


def raise_for_stale_same_script_entries(entries, command):
    """Fail the removal when this script is still registered under another interpreter.

    The exact-command match misses entries written by an install whose python3
    resolved differently; a different source path belongs to another checkout and
    stays untouched.
    """
    try:
        script = shlex.split(command)[1]
    except (IndexError, ValueError):
        return
    stale = [
        item["command"]
        for entry in entries for item in entry["hooks"]
        if script in item.get("command", "") and item.get("command") != command
    ]
    if stale:
        raise ValueError(
            "a Converge hook entry for this script remains with a different interpreter "
            f"or path; re-run with the same python3 in PATH or remove it manually: {stale}"
        )


def update(path, command, event="Stop", remove=False):
    path = Path(path)
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError("hook configuration must be an object")
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hook configuration hooks must be an object")
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        raise ValueError(f"hook configuration {event} must be a list")
    for entry in entries[:]:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list) \
                or any(not isinstance(item, dict) for item in entry["hooks"]):
            raise ValueError("hook configuration Stop entry is invalid")
        entry["hooks"] = [item for item in entry["hooks"] if item.get("command") != command]
        if not entry["hooks"]:
            entries.remove(entry)
    if remove:
        raise_for_stale_same_script_entries(entries, command)
    else:
        entries.append({"hooks": [
            {"type": "command", "command": command, "timeout": HOOK_TIMEOUT_SECONDS}
        ]})
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(value, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--event", default="Stop")
    parser.add_argument("--remove", action="store_true")
    arguments = parser.parse_args()
    update(arguments.config, arguments.command, arguments.event, arguments.remove)


if __name__ == "__main__":
    main()
