#!/usr/bin/env python3
"""Resolve the native TDD coverage command and threshold without executing it."""

import argparse
import json
import re
import shlex
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path


DEFAULT_THRESHOLD = 85
COMMAND_FILE = Path("docs/00_standards/test-commands.yml")
TARGET_FILE = Path("docs/00_standards/quality-targets.yml")
SHELL_SYNTAX = re.compile(r"[|&;<>()`$]")


def config_text(workspace, relative, revision=None):
    if revision is not None:
        result = subprocess.run(
            ['git', '-C', str(workspace), 'show', f'{revision}:{relative}'],
            capture_output=True, check=False,
        )
        return result.stdout.decode('utf-8') if result.returncode == 0 else ''
    path = workspace / relative
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def scalar(content, names):
    pattern = re.compile(r"^\s*(?:" + "|".join(map(re.escape, names)) + r")\s*:\s*(\S.*?)\s*$")
    for line in content.splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip().strip("\"'")
    return None


def target_threshold(workspace, revision=None):
    value = scalar(config_text(workspace, TARGET_FILE, revision), ("coverage", "coverage_min", "line_coverage"))
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
    runner = coverage_runner(argv)
    option = {
        'pytest': '--cov-fail-under', 'py.test': '--cov-fail-under',
        'coverage': '--fail-under', 'coverage.py': '--fail-under',
        'cargo': '--fail-under', 'cargo-tarpaulin': '--fail-under', 'grcov': '--fail-under',
        'vitest': '--coverage.thresholds.lines', 'dotnet': '/p:threshold',
    }.get(runner)
    values = []
    for index, argument in enumerate(argv):
        argument = argument.casefold() if runner == 'dotnet' else argument
        if argument == option:
            values.append(argv[index + 1] if index + 1 < len(argv) else '')
        elif option and argument.startswith(option + '='):
            values.append(argument[len(option) + 1:])
    if not values:
        return None
    if len(values) != 1 or not re.fullmatch(r'[0-9]{1,3}', values[0]) or not 1 <= int(values[0]) <= 100:
        raise ValueError('coverage threshold must be one unambiguous integer in 1..100')
    return int(values[0])


def adapt_coverage_argv(argv, threshold_value):
    runners = {coverage_runner(argv)}
    coverage_enabled = any(argument == "--cov" or argument.startswith("--cov=") for argument in argv)
    if {"pytest", "py.test"} & runners and coverage_enabled:
        return [*argv, f"--cov-fail-under={threshold_value}"]
    if "vitest" in runners and any(argument.startswith("--coverage") for argument in argv):
        return [*('--coverage.enabled' if item == '--coverage' else item for item in argv),
                f"--coverage.thresholds.lines={threshold_value}"]
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
    if '--' in argv:
        return True
    if runner in {'pytest', 'py.test'}:
        enabled = False
        for item in argv:
            if item == '--cov-reset':
                enabled = False
            elif item == '--cov' or item.startswith('--cov='):
                enabled = True
        return not enabled or any(item in argv for item in ('--no-cov', '--collect-only', '--co'))
    if runner == 'dotnet':
        return (len(argv) < 2 or argv[1] != 'test'
                or '/p:collectcoverage=true' not in lowered
                or '/p:collectcoverage=false' in lowered)
    if runner == 'vitest':
        enabled = any(item in lowered for item in ('--coverage', '--coverage=true', '--coverage.enabled', '--coverage.enabled=true'))
        disabled = any(item in lowered for item in ('--no-coverage', '--coverage=false', '--coverage.enabled=false'))
        disabled = disabled or any(
            item in {'--coverage', '--coverage.enabled'} and index + 1 < len(lowered)
            and lowered[index + 1] == 'false' for index, item in enumerate(lowered)
        )
        return not enabled or disabled
    if runner in {'mvn', 'mvnw'}:
        return any(item in lowered for item in ('-djacoco.skip=true', '-dskiptests', '-dskiptests=true', '-dmaven.test.skip=true'))
    if runner in {'gradle', 'gradlew'}:
        return '--dry-run' in argv or '-m' in argv or any(
            item in {'--exclude-task=test', '--exclude-task=jacocoTestCoverageVerification'} for item in argv
        ) or any(
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


def project_gate_threshold(workspace, argv, revision=None):
    runners = {coverage_runner(argv)}
    gate_files = ()
    pattern = None
    if {"mvn", "mvnw"} & runners and "jacoco:check" in argv:
        gate_files = ("pom.xml",)
        pattern = r"<counter>\s*(?:LINE|INSTRUCTION)\s*</counter>.*?<minimum>\s*([0-9.]+)\s*</minimum>"
    elif {"gradle", "gradlew"} & runners and "jacocoTestCoverageVerification" in argv:
        gate_files = ("build.gradle", "build.gradle.kts")
        pattern = r"counter\s*=\s*['\"](?:LINE|INSTRUCTION)['\"].*?minimum\s*=\s*([0-9.]+)"
    if pattern is None:
        return None
    for path in gate_files:
        content = config_text(workspace, path, revision)
        if content:
            thresholds = [
                candidate for candidate in (
                    percentage(match.group(1))
                    for match in re.finditer(pattern, content, re.DOTALL)
                ) if candidate is not None
            ]
            if thresholds:
                return min(thresholds)
    return None


def resolve(workspace, *, revision=None):
    workspace = Path(workspace).expanduser().resolve()
    configured = scalar(config_text(workspace, COMMAND_FILE, revision), ("coverage",))
    target = target_threshold(workspace, revision)
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
        try:
            configured_threshold = explicit_threshold(argv)
        except ValueError as error:
            return {
                'status': 'uncovered', 'source': 'test-commands.yml', 'argv': None,
                'threshold': threshold_value, 'threshold_source': threshold_source,
                'reason': str(error),
            }
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
        project_gate = project_gate_threshold(workspace, argv, revision)
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


def require_matching_coverage(coverage, workspace, *, revision=None):
    policy = resolve(workspace, revision=revision)
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
