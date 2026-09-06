#!/usr/bin/env python3
"""Resolve the native TDD coverage command and threshold without executing it."""

import argparse
import json
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
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
    content = config_text(workspace, TARGET_FILE, revision)
    values = re.findall(r"^[ \t]*(?:coverage|coverage_min|line_coverage)[ \t]*:([^\n]*)$", content, re.MULTILINE)
    if not values:
        return None
    # ponytail: parse literal target values only; extend YAML support when required.
    match = re.fullmatch(r'''(?:"([0-9]{1,3})"|'([0-9]{1,3})'|([0-9]{1,3}))(?:[ \t]+#.*)?''', values[0].strip())
    if len(values) != 1 or match is None:
        raise ValueError("quality-targets.yml coverage must be one literal integer in 1..100")
    candidate = int(next(value for value in match.groups() if value is not None))
    if not 1 <= candidate <= 100:
        raise ValueError("quality-targets.yml coverage must be one literal integer in 1..100")
    return candidate


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
    if any(item in argv for item in ('--', '--help', '-h', '--version')):
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
        return '-v' in argv or any(item in lowered for item in (
            '--fail-never', '-fn', '-djacoco.skip=true', '-djacoco.haltonfailure=false',
            '-dskiptests', '-dskiptests=true', '-dmaven.test.skip=true',
        ))
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
    if {"mvn", "mvnw"} & runners and "jacoco:check" in argv:
        return maven_gate_threshold(config_text(workspace, "pom.xml", revision))
    if {"gradle", "gradlew"} & runners and "jacocoTestCoverageVerification" in argv:
        for path in ("build.gradle", "build.gradle.kts"):
            threshold = gradle_gate_threshold(config_text(workspace, path, revision))
            if threshold is not None:
                return threshold
    return None


def gradle_gate_threshold(content):
    content = re.sub(r'/\*.*?\*/|//[^\n]*', '', content, flags=re.DOTALL)
    thresholds = []
    # Resolve only literal limits; never combine a counter and minimum across sibling limits.
    for body in re.findall(r'\blimit\s*\{([^{}]*)\}', content):
        clauses = [clause.strip() for clause in re.split(r'[;\n]', body) if clause.strip()]
        fields = [re.fullmatch(r'(counter|value|minimum|maximum)\s*=\s*(.+)', clause) for clause in clauses]
        if any(field is None for field in fields):
            continue
        values = {field[1]: field[2].strip() for field in fields}
        if len(values) != len(fields):
            continue
        if values.get('counter', "'INSTRUCTION'") not in {"'LINE'", '"LINE"', "'INSTRUCTION'", '"INSTRUCTION"'} \
                or values.get('value', "'COVEREDRATIO'") not in {"'COVEREDRATIO'", '"COVEREDRATIO"'}:
            continue
        minimum = values.get('minimum', '')
        if not re.fullmatch(r'(?:0?\.\d+|1(?:\.0+)?)(?:\.toBigDecimal\(\))?', minimum):
            continue
        threshold = percentage(minimum.removesuffix('.toBigDecimal()'))
        if threshold is not None:
            thresholds.append(threshold)
    return min(thresholds) if thresholds else None


def maven_gate_threshold(content):
    try:
        project = ET.fromstring(content)
    except ET.ParseError:
        return None
    for element in project.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    if project.tag != 'project':
        return None
    plugins = [plugin for plugin in project.findall('./build/plugins/plugin')
               if plugin.findtext('groupId') == 'org.jacoco'
               and plugin.findtext('artifactId') == 'jacoco-maven-plugin']
    if len(plugins) != 1:
        return None
    plugin = plugins[0]
    # Only a direct literal configuration is resolved; execution overrides need effective-model evidence.
    if any(execution.findtext('id') == 'default-cli' and execution.find('configuration') is not None
           for execution in plugin.findall('./executions/execution')):
        return None
    config = plugin.find('configuration')
    if config is None or config.findtext('skip', 'false').strip().lower() != 'false' \
            or config.findtext('haltOnFailure', 'true').strip().lower() != 'true':
        return None
    thresholds = []
    for limit in config.findall('./rules/rule/limits/limit'):
        if limit.findtext('counter', 'INSTRUCTION').strip() not in {'LINE', 'INSTRUCTION'} \
                or limit.findtext('value', 'COVEREDRATIO').strip() != 'COVEREDRATIO':
            continue
        minimum = limit.findtext('minimum', '').strip()
        threshold = percentage(minimum) if re.fullmatch(r'[0-9.]+', minimum) else None
        if threshold is not None:
            thresholds.append(threshold)
    return min(thresholds) if thresholds else None


def resolve(workspace, *, revision=None):
    workspace = Path(workspace).expanduser().resolve()
    configured = scalar(config_text(workspace, COMMAND_FILE, revision), ("coverage",))
    try:
        target = target_threshold(workspace, revision)
    except ValueError as error:
        return {"status": "uncovered", "source": "quality-targets.yml", "argv": None,
                "threshold": None, "threshold_source": "quality-targets.yml", "reason": str(error)}
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
    from evidence_contract import require_jacoco_execution, validate_observed_evidence_receipt
    require_jacoco_execution(validate_observed_evidence_receipt(coverage["receipt"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("resolve",))
    parser.add_argument("--workspace", required=True)
    arguments = parser.parse_args()
    print(json.dumps(resolve(arguments.workspace), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
