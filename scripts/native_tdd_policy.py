#!/usr/bin/env python3
"""Resolve the native TDD coverage command and threshold without executing it."""

import argparse
import json
import re
import shlex
from decimal import Decimal, InvalidOperation
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
    match = re.search(
        r"(?:fail-under|thresholds\.lines|/p:threshold)\s*(?:=|\s)\s*(\d{1,3})\b",
        value,
        re.IGNORECASE,
    )
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


def explicit_threshold(argv):
    value = threshold(shlex.join(argv))
    if value is None:
        return None
    runners = {coverage_runner(argv)}
    arguments = " ".join(argv).casefold()
    if "/p:threshold" in arguments:
        return value if "dotnet" in runners else None
    if "thresholds.lines" in arguments:
        return value if "vitest" in runners else None
    if "fail-under" in arguments:
        coverage_runners = {
            "pytest", "py.test", "coverage", "coverage.py", "cargo", "cargo-tarpaulin", "grcov",
        }
        return value if runners & coverage_runners else None
    return None


def adapt_coverage_argv(argv, threshold_value):
    runners = {coverage_runner(argv)}
    coverage_enabled = any(argument == "--cov" or argument.startswith("--cov=") for argument in argv)
    if {"pytest", "py.test"} & runners and coverage_enabled:
        return [*argv, f"--cov-fail-under={threshold_value}"]
    if "vitest" in runners and any(argument.startswith("--coverage") for argument in argv):
        return [*argv, f"--coverage.thresholds.lines={threshold_value}"]
    return None


def coverage_runner(argv):
    """Resolve only supported executable/module launch forms, never arbitrary arguments."""
    runner = Path(argv[0]).name.lower()
    if re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', runner):
        return argv[2] if len(argv) > 2 and argv[1] == '-m' else None
    if runner in {'npx', 'pnpm', 'npm'}:
        offset = 2 if len(argv) > 1 and argv[1] == 'exec' else 1
        if runner == 'npm' and offset != 2:
            return None
        return argv[offset] if len(argv) > offset and argv[offset] == 'vitest' else None
    return runner


def collection_disabled(argv):
    runner = coverage_runner(argv)
    lowered = [item.casefold() for item in argv]
    if runner in {'pytest', 'py.test'}:
        return '--no-cov' in argv or not any(item == '--cov' or item.startswith('--cov=') for item in argv)
    if runner == 'dotnet':
        return (len(argv) < 2 or argv[1] != 'test'
                or '/p:collectcoverage=true' not in lowered
                or '/p:collectcoverage=false' in lowered)
    if runner == 'vitest':
        return any(item in lowered for item in ('--no-coverage', '--coverage=false', '--coverage.enabled=false'))
    if runner in {'mvn', 'mvnw'}:
        return any(item in lowered for item in ('-djacoco.skip=true', '-dskiptests', '-dskiptests=true', '-dmaven.test.skip=true'))
    if runner in {'gradle', 'gradlew'}:
        return '--dry-run' in argv or '-m' in argv or any(
            item in {'-x', '--exclude-task'} and index + 1 < len(argv)
            and argv[index + 1] in {'test', 'jacocoTestCoverageVerification'}
            for index, item in enumerate(argv)
        )
    return False


def percentage(value):
    try:
        candidate = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if Decimal("0") < candidate <= Decimal("1"):
        candidate *= 100
    if not Decimal("1") <= candidate <= Decimal("100"):
        return None
    return int(candidate)


def project_gate_threshold(workspace, argv):
    runners = {coverage_runner(argv)}
    gate_files = ()
    pattern = None
    if {"mvn", "mvnw"} & runners and "jacoco:check" in argv:
        gate_files = (workspace / "pom.xml",)
        pattern = r"<counter>\s*(?:LINE|INSTRUCTION)\s*</counter>.*?<minimum>\s*([0-9.]+)\s*</minimum>"
    elif {"gradle", "gradlew"} & runners and "jacocoTestCoverageVerification" in argv:
        gate_files = (workspace / "build.gradle", workspace / "build.gradle.kts")
        pattern = r"counter\s*=\s*['\"](?:LINE|INSTRUCTION)['\"].*?minimum\s*=\s*([0-9.]+)"
    if pattern is None:
        return None
    for path in gate_files:
        if path.is_file():
            thresholds = [
                candidate for candidate in (
                    percentage(match.group(1))
                    for match in re.finditer(pattern, path.read_text(encoding="utf-8"), re.DOTALL)
                ) if candidate is not None
            ]
            if thresholds:
                return min(thresholds)
    return None


def resolve(workspace):
    workspace = Path(workspace).expanduser().resolve()
    configured = scalar(workspace / COMMAND_FILE, ("coverage",))
    target = target_threshold(workspace)
    threshold_value, threshold_source = resolved_threshold(None, target)
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
        if collection_disabled(argv):
            return {
                'status': 'uncovered', 'source': 'test-commands.yml', 'argv': None,
                'threshold': threshold_value, 'threshold_source': threshold_source,
                'reason': 'coverage command cannot enforce coverage: collection or verification is disabled',
            }
        configured_threshold = explicit_threshold(argv)
        threshold_value, threshold_source = resolved_threshold(configured_threshold, target)
        if configured_threshold:
            return {
                "status": "ready", "source": "test-commands.yml", "argv": argv,
                "threshold": threshold_value, "threshold_source": threshold_source,
            }
        adapted = adapt_coverage_argv(argv, threshold_value)
        if adapted:
            return {
                "status": "ready", "source": "test-commands.yml", "argv": adapted,
                "threshold": threshold_value, "threshold_source": "adapter",
            }
        project_gate = project_gate_threshold(workspace, argv)
        if project_gate is not None and project_gate >= threshold_value:
            return {
                "status": "ready", "source": "test-commands.yml", "argv": argv,
                "threshold": project_gate, "threshold_source": "project-coverage-config",
            }
        if project_gate is not None:
            return {
                "status": "uncovered", "source": "test-commands.yml", "argv": None,
                "threshold": threshold_value, "threshold_source": threshold_source,
                "reason": "project coverage gate is below the resolved threshold",
            }
        return {
            "status": "uncovered", "source": "test-commands.yml", "argv": None,
            "threshold": threshold_value, "threshold_source": threshold_source,
            "reason": "coverage command cannot enforce the resolved threshold",
        }
    return {
        "status": "uncovered", "source": "quality-targets.yml" if target else "default", "argv": None,
        "threshold": threshold_value, "threshold_source": threshold_source,
        "reason": "no executable coverage command is configured",
    }


def require_matching_coverage(coverage, workspace):
    policy = resolve(workspace)
    if policy['status'] != 'ready':
        raise ValueError('native coverage policy is not ready')
    if coverage['threshold'] != policy['threshold'] or coverage['receipt']['argv'] != policy['argv']:
        raise ValueError('coverage receipt does not match the resolved native coverage command')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("resolve",))
    parser.add_argument("--workspace", required=True)
    arguments = parser.parse_args()
    print(json.dumps(resolve(arguments.workspace), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
