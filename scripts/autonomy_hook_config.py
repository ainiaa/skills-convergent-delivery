#!/usr/bin/env python3
"""Install or remove one exact Converge Hook entry without touching peers."""

import argparse
import json
import os
import shlex
import tempfile
from pathlib import Path


HOOK_TIMEOUT_SECONDS = 30
CODEX_PYTHON_FLAGS = ["-E", "-S", "-B"]
RECORD_FIELDS = {"Stop": "stop_command", "UserPromptSubmit": "prompt_command"}


def command_arguments(command):
    try:
        return shlex.split(command)
    except ValueError:
        return []


def without_python_flags(args):
    return args[:1] + args[4:] if args[1:4] == CODEX_PYTHON_FLAGS else args


def matches_codex_command(args, target):
    return bool(args) and Path(args[0]).name == "python3" and without_python_flags(args)[1:] == target[1:]


def codex_stop_wrapper(existing, legacy, previous, adapter):
    # Keep the local Stop adapter only when it wraps an exact owned command.
    outer = without_python_flags(command_arguments(existing))
    if outer[1:3] != [str(adapter), "approve"]:
        return None
    if Path(outer[0]).name != "python3" and existing != previous:
        return None
    inner = without_python_flags(outer[3:])
    owned = without_python_flags(command_arguments(previous)) if previous else []
    if owned[1:3] == outer[1:3]:
        owned = without_python_flags(owned[3:])
    return outer[1:3] if inner and (inner == owned or matches_codex_command(inner, legacy)) else None


def raise_for_stale_same_script_entries(entries, command):
    """Fail the removal when this script is still registered under another interpreter.

    The exact-command match misses entries written by an install whose python3
    resolved differently; a different source path belongs to another checkout and
    stays untouched.
    """
    args = without_python_flags(command_arguments(command))
    if len(args) < 2:
        return
    stale = [
        item["command"]
        for entry in entries for item in entry["hooks"]
        if isinstance(item.get("command"), str)
        and matches_codex_command(command_arguments(item["command"]), args)
        and item["command"] != command
    ]
    if stale:
        raise ValueError(
            "a Converge hook entry for this script remains with a different interpreter "
            f"or path; re-run with the same python3 in PATH or remove it manually: {stale}"
        )


def update(path, command, event="Stop", remove=False, *, previous=None, legacy=None, codex_adapter=None):
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
    registered = None
    for entry in entries[:]:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list) \
                or any(not isinstance(item, dict) for item in entry["hooks"]):
            raise ValueError(f"hook configuration {event} entry is invalid")
        before = len(entry["hooks"])
        for item in entry["hooks"][:]:
            existing = item.get("command")
            if item.get("type") != "command" or not isinstance(existing, str):
                continue
            replacement = None
            if codex_adapter is not None:
                wrapper = codex_stop_wrapper(existing, legacy, previous, codex_adapter)
                if wrapper and remove:
                    replacement = command
                elif wrapper:
                    if not codex_adapter.is_file():
                        raise ValueError(f"registered Converge Stop adapter is missing: {codex_adapter}")
                    target = command_arguments(command)
                    replacement = shlex.join([target[0], *CODEX_PYTHON_FLAGS, *wrapper, *target])
            if replacement is None and (existing in (command, previous)
                                        or (legacy and matches_codex_command(command_arguments(existing), legacy))):
                replacement = command
            if replacement is None:
                continue
            if remove or registered == replacement:
                entry["hooks"].remove(item)
            elif registered is not None:
                raise ValueError(f"multiple Converge registrations match the {event} event")
            else:
                item["command"] = registered = replacement
        if before and not entry["hooks"]:
            entries.remove(entry)
    if remove:
        raise_for_stale_same_script_entries(entries, command)
    elif registered is None:
        entries.append({"hooks": [
            {"type": "command", "command": command, "timeout": HOOK_TIMEOUT_SECONDS}
        ]})
        registered = command
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
    return registered


def record_command(path, runtime, event, command):
    """Persist the exact registered command per event so removal survives drift."""
    path = Path(path)
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError("hook record must be an object")
    field = RECORD_FIELDS.get(event)
    if field is None:
        raise ValueError(f"hook record does not track the {event} event")
    entry = value.setdefault(runtime, {})
    entry[field] = command
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


def recorded_command(path, runtime, which):
    """Return the recorded exact command for a runtime, or None when absent."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        command = value.get(runtime, {}).get(which)
    except (OSError, ValueError):
        return None
    return command if isinstance(command, str) and command else None


def drop_record(path, runtime):
    """Remove one runtime's record; delete the file when the last entry goes."""
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(value, dict) and value.pop(runtime, None) is not None:
        if value:
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
        else:
            path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--event", default="Stop")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--record-state")
    parser.add_argument("--record-runtime")
    parser.add_argument("--record-event", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    command = arguments.command
    previous = None
    legacy = None
    adapter = None
    argv = command_arguments(command)
    managed_codex = (arguments.record_state and arguments.record_runtime == "codex"
                     and (arguments.remove or argv[1:4] == CODEX_PYTHON_FLAGS))
    if managed_codex:
        legacy = without_python_flags(argv)
        previous = command if arguments.remove else recorded_command(
            arguments.record_state, "codex", RECORD_FIELDS[arguments.event],
        )
        if arguments.event == "Stop":
            adapter = Path(arguments.config).parent / "hook-adapters/codex_stop_adapter.py"
    registered = update(arguments.config, command, arguments.event, arguments.remove,
                        previous=previous, legacy=legacy, codex_adapter=adapter)
    if arguments.record_state:
        if not arguments.record_runtime:
            raise ValueError("--record-state requires --record-runtime")
        if arguments.remove:
            drop_record(arguments.record_state, arguments.record_runtime)
        else:
            record_command(
                arguments.record_state, arguments.record_runtime,
                arguments.event, registered,
            )
    if managed_codex and not arguments.remove:
        print(registered)


if __name__ == "__main__":
    main()
