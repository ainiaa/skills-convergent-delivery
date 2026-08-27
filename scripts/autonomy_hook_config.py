#!/usr/bin/env python3
"""Install or remove Converge's exact Stop-hook entry without touching peers."""

import argparse
import json
import os
import tempfile
from pathlib import Path


def update(path, command, remove=False):
    path = Path(path)
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError("hook configuration must be an object")
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hook configuration hooks must be an object")
    entries = hooks.setdefault("Stop", [])
    if not isinstance(entries, list):
        raise ValueError("hook configuration Stop must be a list")
    for entry in entries[:]:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list) \
                or any(not isinstance(item, dict) for item in entry["hooks"]):
            raise ValueError("hook configuration Stop entry is invalid")
        entry["hooks"] = [item for item in entry["hooks"] if item.get("command") != command]
        if not entry["hooks"]:
            entries.remove(entry)
    if not remove:
        entries.append({"hooks": [{"type": "command", "command": command}]})
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
    parser.add_argument("--remove", action="store_true")
    arguments = parser.parse_args()
    update(arguments.config, arguments.command, arguments.remove)


if __name__ == "__main__":
    main()
