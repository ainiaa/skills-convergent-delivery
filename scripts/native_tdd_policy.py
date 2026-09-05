#!/usr/bin/env python3
"""Resolve the native TDD coverage command and threshold without executing it."""

import argparse
import json
import re
import shlex
from pathlib import Path


DEFAULT_THRESHOLD = 85
COMMAND_FILE = Path("docs/00_standards/test-commands.yml")
TARGET_FILE = Path("docs/00_standards/quality-targets.yml")
SHELL_SYNTAX = re.compile(r"[|&;<>()`$]")


def scalar(path, names):
    if not path.is_file():
        return None
    pattern = re.compile(r"^\s*(?:" + "|".join(map(re.escape, names)) + r")\s*:\s*(\S.*?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip().strip("\"'")
    return None


def threshold(value):
    if value is None:
        return None
    match = re.search(r"(?:fail-under|thresholds\.lines)\s*(?:=|\s)\s*(\d{1,3})\b", value)
    if not match:
        return None
    candidate = int(match.group(1))
    return candidate if 1 <= candidate <= 100 else None


def target_threshold(workspace):
    value = scalar(workspace / TARGET_FILE, ("coverage", "coverage_min", "line_coverage"))
    if value is None or not value.isdigit():
        return None
    candidate = int(value)
    return candidate if 1 <= candidate <= 100 else None


def resolved_threshold(command_threshold, target):
    if command_threshold:
        return command_threshold, "argv"
    if target:
        return target, "quality-targets.yml"
    return DEFAULT_THRESHOLD, "default"


def resolve(workspace):
    workspace = Path(workspace).expanduser().resolve()
    configured = scalar(workspace / COMMAND_FILE, ("coverage",))
    configured_threshold = threshold(configured)
    target = target_threshold(workspace)
    threshold_value, threshold_source = resolved_threshold(configured_threshold, target)
    if configured:
        if SHELL_SYNTAX.search(configured):
            return {
                "status": "uncovered", "source": "test-commands.yml", "argv": None,
                "threshold": threshold_value, "threshold_source": threshold_source,
                "reason": "coverage command contains unsupported shell syntax",
            }
        try:
            argv = shlex.split(configured)
        except ValueError:
            argv = []
        if not argv:
            return {
                "status": "uncovered", "source": "test-commands.yml", "argv": None,
                "threshold": threshold_value, "threshold_source": threshold_source,
                "reason": "coverage command is not a non-empty argv",
            }
        return {
            "status": "ready", "source": "test-commands.yml", "argv": argv,
            "threshold": threshold_value, "threshold_source": threshold_source,
        }
    return {
        "status": "ready", "source": "quality-targets.yml" if target else "default", "argv": None,
        "threshold": threshold_value, "threshold_source": threshold_source,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("resolve",))
    parser.add_argument("--workspace", required=True)
    arguments = parser.parse_args()
    print(json.dumps(resolve(arguments.workspace), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
