#!/usr/bin/env python3
"""Bounded same-thread interaction evaluation in disposable fixture workspaces."""

import argparse
import hashlib
import json
import math
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from host_bridge import CodexSession
from run_contract import followup_action
from evidence_contract import _run_command, test_execution_result


CASES = {
    "product-decisions": [
        "修订 product-decisions.json 的三份 Product 决策摘要，依据 product-inputs.json，保留其对象和字段。"
        "资料明确的规则直接沿用；缺少审批阈值或重试审批决定时保留未决并提出相应问题。"
        "只有输入明确主管缺失才提出该问题；不得将重试免审批写成已定规则。"
        "一次完成全部摘要并复核，不修改输入，不新增业务规则。只交付结构化摘要，不生成完整 PRD。",
    ],
    "full-flow-review": [
        "继续当前已授权的配置流程修复，再仔细审查完整流程。已决定所有入口只接受 command 为非空白字符串的配置；"
        "扫描跳过无效候选，其他入口拒绝无效配置，失败保存或切换不得破坏当前配置。"
        "扫描与试调用已经修复，请检查实际调用链并修复同范围遗漏，验证后报告证据和未验证路径。不要启动真实程序。",
    ],
    "simple-local-fix": [
        "修复 status_normalizer.py 的局部 None bug：None 返回空字符串，保持 strip/lower。"
        "按 TDD 补测试并验证；范围仅 status_normalizer.py 和 test_status_normalizer.py，验证后结束。",
    ],
    "review-defect": ["修复状态标准化：None 返回空字符串，保持 strip/lower 行为。补测试并验证。",
                      "仔细审查当前实现，还有没有其他问题？"],
    "clean-review": ["实现已经修复，请验证当前状态标准化行为。", "在同一事项上再复核一次。"],
    "known-decision": ["已决定：None 返回空字符串，不增加依赖。请记录这个约束，不修改文件。",
                       "按已决定的兼容方案完成 None 修复。"],
    "new-decision": ["既有 None 与字符串行为已经正确。仅审查，不修改。",
                     "现在还要支持数字输入，但数字转字符串还是拒绝尚未决定。给出推荐并询问，不要修改。"],
    "no-progress": ["修复 None 返回空字符串并保持 strip/lower 行为，补测试并验证。"],
    "independent-decisions": [
        "先讨论，不写文件。None 返回值是空字符串还是报错、字符串是否保留首尾空白，是两个互不依赖的业务选择；都未决定。请同轮给出推荐并询问。",
        "两项已决定：None 返回空字符串，字符串保留现有 strip/lower。不增加依赖，按决定实现并验证。",
    ],
    "dependent-decisions": [
        "只讨论，不写文件。先决定是否支持数字；只有支持数字才需要决定小数格式。请先问当前可决定的问题，给推荐，后置依赖问题。",
        "决定支持数字。小数的展示格式仍需我决定；请给推荐并询问，继续不写文件。",
    ],
}
DECISION_CHECKPOINTS = {
    "known-decision": [(), ()],
    "new-decision": [(), ("number_handling",)],
    "independent-decisions": [("none_result", "whitespace"), ()],
    "dependent-decisions": [("support_numbers",), ("decimal_format",)],
}
DECISION_REPLY = (
    '\n讨论回执仅返回 JSON {"decision_requests":[{"id":"事项标识","recommendation":"推荐方案"}]}。'
    '没有待决事项时返回空列表。事项标识：none_result（None 返回值）、whitespace（空白处理）、'
    'number_handling（数字转换或拒绝）、support_numbers（是否支持数字）、decimal_format（小数格式）。'
    '只列当前需要用户决定的事项；已决或依赖尚未成立的后置事项不列。'
)
GOOD = 'def normalize_status(value):\n    return "" if value is None else value.strip().lower()\n'
BROKEN = 'def normalize_status(value):\n    return value.strip().lower()\n'
REVIEW_DEFECT = 'def normalize_status(value):\n    return "" if value is None else value.lower()\n'
# This judge is evaluator-owned: it never imports tests written by the candidate.
JUDGE = ('import sys; sys.path.insert(0, sys.argv[1]); '
         'from status_normalizer import normalize_status as n; '
         'assert n(None) == ""; assert n(" Active ") == "active"; '
         'assert n("") == ""; assert n("  ") == ""')
# This constrained fixture checks source-grounded decisions, not arbitrary PRD prose.
PRODUCT_INPUTS = {
    "unresolved": {"approval_threshold": None, "retry_approval": None, "manager_missing": False},
    "explicit-manager-missing": {"approval_threshold": 100, "retry_approval": "reuse", "manager_missing": True},
    "sufficient": {"approval_threshold": 100, "retry_approval": "reuse", "manager_missing": False},
}
PRODUCT_GOOD = json.dumps({key: {
    "approval_threshold": source["approval_threshold"],
    "retry_approval": source["retry_approval"],
    "questions": (["approval-threshold"] if source["approval_threshold"] is None else [])
                 + (["retry-approval"] if source["retry_approval"] is None else [])
                 + (["manager-missing"] if source["manager_missing"] else []),
} for key, source in PRODUCT_INPUTS.items()})
PRODUCT_BROKEN = json.loads(PRODUCT_GOOD)
PRODUCT_BROKEN["unresolved"].update(retry_approval="waived", questions=["approval-threshold", "manager-missing"])
PRODUCT_BROKEN = json.dumps(PRODUCT_BROKEN)
PRODUCT_JUDGE = '''import json
from pathlib import Path
drafts = json.loads((Path(sys.argv[1]) / "product-decisions.json").read_text())
assert set(drafts) == set(inputs)
for key, source in inputs.items():
    draft = drafts[key]
    assert set(draft) == {"approval_threshold", "retry_approval", "questions"}, key
    assert draft["approval_threshold"] == source["approval_threshold"], key
    assert draft["retry_approval"] == source["retry_approval"], key
    expected = (["approval-threshold"] if source["approval_threshold"] is None else [])
    expected += (["retry-approval"] if source["retry_approval"] is None else [])
    expected += (["manager-missing"] if source["manager_missing"] else [])
    assert sorted(draft["questions"]) == sorted(expected), key
assert json.loads((Path(sys.argv[1]) / "product-inputs.json").read_text()) == inputs
'''
# Keep fixture and judge self-contained in frozen host-eval snapshots.
FLOW_SOURCE = '''"""Synthetic configuration flow; every entry must reject a missing/blank command.

No command is executed. scan/probe are fixed; the shared manual entry still
bypasses validation, including persistence, switching and startup callers.
"""

import json


def validate(config):
    if not isinstance(config, dict):
        raise ValueError("configuration must be an object")
    command = config.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a nonblank string")
    return dict(config)


def scan(configs):
    found = []
    for config in configs:
        try:
            found.append(validate(config))
        except ValueError:
            continue
    return found


def probe(config):
    return validate(config)


def manual(config):
    return config


def save(config, path):
    path.write_text(json.dumps(manual(config)))


def restore(path):
    return manual(json.loads(path.read_text()))


def select(current, candidate):
    return manual(candidate)


def start(config):
    return manual(config)["command"]
'''
FLOW_JUDGE = '''"""Evaluator-owned outcome checks, executed outside the candidate workspace."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, sys.argv.pop(1))
import configuration as flow


VALID = {"command": "synthetic-tool", "name": "example"}
INVALID = (None, [], "tool", {}, {"command": None}, {"command": 1},
           {"command": ""}, {"command": " \\t\\n"})


class ConfigurationFlowTest(unittest.TestCase):
    def test_scan_filters_invalid_candidates(self):
        self.assertEqual([VALID], flow.scan([*INVALID, VALID]))
        self.assertEqual([], flow.scan([]))

    def test_probe_and_manual_use_the_same_rule(self):
        for entry in (flow.probe, flow.manual):
            self.assertEqual(VALID, entry(VALID))
            for config in INVALID:
                with self.subTest(entry=entry.__name__, config=config), self.assertRaises(ValueError):
                    entry(config)

    def test_save_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "configuration.json"
            flow.save(VALID, path)
            self.assertEqual(VALID, json.loads(path.read_text()))
            self.assertEqual(VALID, flow.restore(path))

    def test_invalid_save_preserves_the_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "configuration.json"
            original = json.dumps(VALID)
            path.write_text(original)
            for config in INVALID:
                with self.subTest(config=config):
                    with self.assertRaises(ValueError):
                        flow.save(config, path)
                    self.assertEqual(original, path.read_text())

    def test_restore_revalidates_persisted_and_malformed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "configuration.json"
            for raw in [*(json.dumps(value) for value in INVALID), "{broken"]:
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    with self.assertRaises(ValueError):
                        flow.restore(path)
                    self.assertEqual(raw, path.read_text())

    def test_failed_switch_preserves_the_current_configuration(self):
        current = dict(VALID)
        candidate = {"command": "another-tool"}
        self.assertEqual(candidate, flow.select(current, candidate))
        for config in INVALID:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    flow.select(current, config)
                self.assertEqual(VALID, current)

    def test_start_rechecks_the_rule_without_executing_a_command(self):
        self.assertEqual(VALID["command"], flow.start(VALID))
        for config in INVALID:
            with self.subTest(config=config), self.assertRaises(ValueError):
                flow.start(config)

    def test_persistence_io_errors_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                flow.save(VALID, Path(directory))
            with self.assertRaises(OSError):
                flow.restore(Path(directory) / "missing.json")


if __name__ == "__main__":
    unittest.main()
'''


def source_fingerprint(workspace):
    files = sorted(path for path in workspace.rglob("*")
                   if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts)
    return hashlib.sha256(b"".join(path.relative_to(workspace).as_posix().encode() + b"\0"
                                   + path.read_bytes() for path in files)).hexdigest()


def judge(workspace, *, no_progress=False, full_flow=False, product=False, deadline=None):
    workspace = Path(workspace).resolve()
    timeout = 10 if deadline is None else min(10, deadline - time.monotonic())
    if timeout <= 0:
        raise TimeoutError("interaction evaluation deadline expired")
    code = PRODUCT_JUDGE if product else JUDGE
    code += '\nassert False, "frozen external verification failure"' if no_progress else ''
    code = FLOW_JUDGE if full_flow else (
        'import sys, unittest\n'
        f'code = {code!r}\ninputs = {PRODUCT_INPUTS!r}\n'
        'result = unittest.TextTestRunner().run(unittest.FunctionTestCase(lambda: exec(code)))\n'
        'sys.exit(0 if result.wasSuccessful() else 1)\n'
    )
    exit_code, stdout, stderr = _run_command(
        workspace, [sys.executable, "-B", "-c", code, str(workspace)], timeout,
    )
    counts = test_execution_result([sys.executable, "-m", "unittest"], stdout, stderr)
    valid = counts is not None and not any(counts[key] for key in ("skipped", "xfailed", "xpassed"))
    outcome = ("pass" if valid and exit_code == 0 and counts["passed"] > 0
               and not counts["errors"] and not counts["failed"] else
               "fail" if valid and exit_code == 1 and counts["failed"] + counts["errors"] > 0 else "uncovered")
    return {"exit_code": exit_code,
            "outcome": outcome, "test_check": counts,
            "stdout_fingerprint": hashlib.sha256(stdout).hexdigest(),
            "stderr_fingerprint": hashlib.sha256(stderr).hexdigest()}


def local_tdd(workspace, items, deadline=None):
    # shortcut: this fixture observes direct unittest and apply_patch events; extend with another fixture runner.
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        return {"outcome": "uncovered", "reason": "host_execution_items_unavailable"}
    red, green, changed = None, None, False
    for item in items:
        if item.get("type") == "fileChange" and item.get("status") == "completed":
            changes = item.get("changes")
            if not isinstance(changes, list) or any(not isinstance(change, dict)
                    or not isinstance(change.get("path"), str) for change in changes):
                return {"outcome": "uncovered", "reason": "host_file_changes_unavailable"}
            for change in changes:
                path = Path(change["path"])
                path = (workspace / path).resolve()
                if path == workspace / "test_status_normalizer.py" and red is not None:
                    return {"outcome": "fail", "reason": "tests_changed_after_red"}
                if path == workspace / "status_normalizer.py":
                    if red is None:
                        return {"outcome": "fail", "reason": "implementation_before_red"}
                    changed, green = True, None
        if item.get("type") != "commandExecution":
            continue
        if item.get("status") not in ("completed", "failed") \
                or not isinstance(item.get("command"), str) \
                or not item["command"].strip() or '\x00' in item["command"] \
                or not isinstance(item.get("cwd"), str) or not item["cwd"]:
            return {"outcome": "uncovered", "reason": "host_command_observation_unavailable"}
        try:
            argv = shlex.split(item.get("command", ""))
            if len(argv) == 3 and Path(argv[0]).name in {"sh", "bash", "zsh"} and argv[1] in {"-c", "-lc"}:
                argv = shlex.split(argv[2])
        except (ValueError, TypeError):
            return {"outcome": "uncovered", "reason": "host_command_observation_unavailable"}
        if len(argv) > 1 and argv[1] == "-B":
            argv = [argv[0], *argv[2:]]
        python_unittest = len(argv) >= 3 and re.fullmatch(
            r"python(?:\d+(?:\.\d+)*)?", Path(argv[0]).name) and argv[1:3] == ["-m", "unittest"]
        if python_unittest:
            argv = [*argv[:3], *(value for value in argv[3:] if value not in {"-v", "-q"})]
            if any(target in argv[3:] for target in ("test_status_normalizer", "test_status_normalizer.py")) \
                    and len(argv) != 4 and item.get("cwd") and Path(item["cwd"]).resolve() == workspace:
                return {"outcome": "uncovered", "reason": "unsupported_unittest_observation"}
        if len(argv) != 4 or not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(argv[0]).name) \
                or argv[1:3] != ["-m", "unittest"] or argv[3] not in {"test_status_normalizer", "test_status_normalizer.py"} \
                or not isinstance(item.get("cwd"), str) or not item["cwd"] \
                or Path(item.get("cwd", "")).resolve() != workspace:
            continue
        if changed:
            green = None
        output = item.get("aggregatedOutput")
        if not isinstance(output, str) or type(item.get("exitCode")) is not int:
            return {"outcome": "uncovered", "reason": "host_command_result_unavailable"}
        counts = test_execution_result(argv, output.encode(), b"")
        if counts is None or any(counts[key] for key in ("skipped", "xfailed", "xpassed")):
            continue
        if not changed and item.get("exitCode") == 1 and counts["failed"] + counts["errors"] > 0:
            red = counts
        elif changed and item.get("exitCode") == 0 and counts["passed"] > 0 \
                and not counts["failed"] and not counts["errors"]:
            green = counts
    if red is None or green is None:
        return {"outcome": "fail", "reason": "observed_red_change_green_required"}
    test_file = workspace / "test_status_normalizer.py"
    if not test_file.is_file() or test_file.is_symlink():
        return {"outcome": "fail", "reason": "regression_test_required"}
    # Execute the same candidate tests against both sources, outside its workspace.
    with tempfile.TemporaryDirectory(prefix="converge-local-tdd-") as directory:
        probe = Path(directory)
        (probe / test_file.name).write_bytes(test_file.read_bytes())
        for content, expected_code in ((BROKEN, 1), ((workspace / "status_normalizer.py").read_text(), 0)):
            timeout = 10 if deadline is None else min(10, deadline - time.monotonic())
            if timeout <= 0:
                raise TimeoutError("interaction evaluation deadline expired")
            (probe / "status_normalizer.py").write_text(content)
            argv = [sys.executable, "-m", "unittest", "test_status_normalizer"]
            observation = {}
            code, stdout, stderr = _run_command(
                probe, [sys.executable, "-B", *argv[1:]], timeout, observation=observation,
            )
            counts = test_execution_result(argv, stdout, stderr)
            if observation:
                return {"outcome": "uncovered", "reason": "candidate_test_runner_unavailable"}
            if code != expected_code or counts is None or any(counts[key] for key in ("skipped", "xfailed", "xpassed")) \
                    or (code == 0 and (not counts["passed"] or counts["failed"] or counts["errors"])) \
                    or (code == 1 and not counts["failed"] + counts["errors"]):
                return {"outcome": "fail", "reason": "candidate_tests_do_not_distinguish_the_fix"}
    return {"outcome": "pass", "red": red, "green": green}


def replay(case, workspace, session, *, controlled=False, capture_synthetic=False):
    if case not in CASES or type(controlled) is not bool:
        raise ValueError("invalid replay case or mode")
    workspace = Path(workspace)
    if any(workspace.iterdir()):
        raise ValueError("replay requires an empty disposable workspace")
    full_flow = case == "full-flow-review"
    product = case == "product-decisions"
    path = workspace / ("product-decisions.json" if product else
                        "configuration.py" if full_flow else "status_normalizer.py")
    path.write_text(PRODUCT_BROKEN if product else FLOW_SOURCE if full_flow else
                    GOOD if case in {"clean-review", "new-decision"} else BROKEN)
    if product:
        (workspace / "product-inputs.json").write_text(json.dumps(PRODUCT_INPUTS))
    result = {"case": case, "mode": "controlled" if controlled else "guided",
              "result": "pass", "turns": [], "automatic_repairs": 0,
              "controller_actions": [], "evidence_level": "process_observed"}
    task_id = None
    trajectory = []
    deadline = getattr(session, "deadline", None)
    try:
        # Exercise the actual interpreter and frozen judge before any model call.
        with tempfile.TemporaryDirectory(prefix="converge-verifier-preflight-") as directory:
            probe = Path(directory)
            if product:
                (probe / "product-inputs.json").write_text(json.dumps(PRODUCT_INPUTS))
            for expected, content in (("pass", PRODUCT_GOOD if product else
                                       FLOW_SOURCE.replace("return config\n", "return validate(config)\n")
                                       if full_flow else GOOD),
                                      ("fail", PRODUCT_BROKEN if product else FLOW_SOURCE if full_flow else REVIEW_DEFECT)):
                (probe / path.name).write_text(content)
                if judge(probe, full_flow=full_flow, product=product, deadline=deadline)["outcome"] != expected:
                    result.update(result="uncovered", failure_kind="environment_invalid",
                                  reason="frozen verifier failed its positive/negative control")
                    return result
        for index, prompt in enumerate(CASES[case]):
            checkpoints = DECISION_CHECKPOINTS.get(case, [])
            expected_decisions = checkpoints[index] if index < len(checkpoints) else None
            if expected_decisions is not None:
                prompt += DECISION_REPLY
            if case == "simple-local-fix":
                prompt += (" 测试用标准库 unittest，直接运行 python -m unittest test_status_normalizer；"
                           "文件修改使用 apply_patch。先观察 RED，再修改生产文件并观察 GREEN。")
            injected = case == "review-defect" and index == 1
            if injected:
                path.write_text(REVIEW_DEFECT)
            # One repair budget belongs to this checkpoint; never reset it inside a retry.
            remaining = 1
            prompt_origin = "user"
            while True:
                before = source_fingerprint(workspace)
                observed = session.turn(prompt)
                if capture_synthetic:
                    trajectory.extend([{"role": "user", "content": prompt},
                                       {"role": "assistant", "content": getattr(session, "last_text", "")}])
                    result["synthetic_trajectory"] = trajectory
                if observed.get("status") != "completed" or not observed.get("task_id") \
                        or task_id is not None and observed["task_id"] != task_id:
                    result.update(result="uncovered", reason="host_not_completed_or_identity_changed")
                    return result
                task_id = observed["task_id"]
                verification = judge(workspace, no_progress=case == "no-progress", full_flow=full_flow,
                                     product=product, deadline=deadline)
                after = source_fingerprint(workspace)
                record = {**observed, "checkpoint": index + 1, "injected_defect": int(injected),
                          "prompt_origin": prompt_origin,
                          "writes": before != after, "source_before": before, "source_after": after,
                          "verification": verification}
                result["turns"].append(record)
                if case == "simple-local-fix" and any(
                    item.is_file() and not {".git", "__pycache__", ".pytest_cache"}.intersection(item.parts)
                    and item.relative_to(workspace).as_posix() not in
                    {"status_normalizer.py", "test_status_normalizer.py"}
                    for item in workspace.rglob("*")
                ):
                    result.update(result="fail", reason="unexpected_local_artifacts")
                    return result
                discussion = case in {"new-decision", "dependent-decisions"} or \
                    case in {"known-decision", "independent-decisions"} and index == 0
                if (discussion or case == "clean-review") and record["writes"]:
                    result["result"] = "fail"
                    return result
                if expected_decisions is not None:
                    items = getattr(session, "last_items", [])
                    messages = [item for item in items if isinstance(item, dict)
                                and item.get("type") == "agentMessage"] if isinstance(items, list) else []
                    answers = [item for item in messages if item.get("phase") == "final_answer"] \
                        or [item for item in messages if item.get("phase") is None]
                    response_text = answers[-1].get("text", "") if answers else \
                        "" if messages else getattr(session, "last_text", "")
                    try:
                        response = json.loads(response_text)
                    except (ValueError, TypeError):
                        response = None
                    requests = response.get("decision_requests") if isinstance(response, dict) else None
                    if not isinstance(response, dict) or set(response) != {"decision_requests"} \
                            or not isinstance(requests, list) or len(requests) != len(expected_decisions) \
                            or not all(isinstance(item, dict) and set(item) == {"id", "recommendation"}
                                       and isinstance(item["id"], str)
                                       and isinstance(item["recommendation"], str)
                                       and item["recommendation"].strip() for item in requests) \
                            or {item["id"] for item in requests} != set(expected_decisions):
                        result.update(result="fail", failure_kind="behavior_failed",
                                      reason="decision_requests_mismatch")
                        return result
                    record["decision_requests"] = requests
                if discussion:
                    break
                if verification["outcome"] == "uncovered":
                    result.update(result="uncovered", failure_kind="evidence_unavailable",
                                  reason="verifier did not produce a valid behavior verdict")
                    return result
                tdd = local_tdd(workspace.resolve(), getattr(session, "last_items", None), deadline) \
                    if case == "simple-local-fix" and verification["outcome"] == "pass" else None
                if tdd is not None:
                    record["tdd"] = tdd
                    if tdd["outcome"] == "uncovered":
                        result.update(result="uncovered", failure_kind="evidence_unavailable", reason=tdd["reason"])
                        return result
                failed = verification["outcome"] == "fail"
                failed |= tdd is not None and tdd["outcome"] == "fail"
                if not failed:
                    break
                if not controlled:
                    result.update(result="fail", failure_kind="behavior_failed")
                    return result
                next_action = followup_action(task_id=task_id, open_issues=["frozen verification failed"],
                                              repair_budget_remaining=remaining)
                result["controller_actions"].append(next_action)
                if next_action["action"] == "block":
                    result.update(result="blocked", failure_kind="behavior_failed", reason=next_action["reason"])
                    return result
                remaining = 0
                prompt_origin = "controller"
                result["automatic_repairs"] += 1
                prompt = ("Controller verification rejected the result. This is the same authorized task. "
                          "None must return an empty string; text must preserve strip/lower. "
                          "The compatibility decision is already resolved. Repair and verify within the "
                          "existing scope now. This is the sole repair attempt; do not request reauthorization.")
                if full_flow or product or case == "simple-local-fix":
                    prompt = CASES[case][0] + "\nController verification rejected the result. This is the sole repair attempt."
                if expected_decisions is not None:
                    prompt += DECISION_REPLY
        return result
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result.update(result="uncovered", failure_kind="evidence_unavailable", reason=str(error))
        return result
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--case", choices=tuple(CASES), default="review-defect")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--controlled", action="store_true")
    parser.add_argument("--allow-execute", action="store_true")
    arguments = parser.parse_args()
    if not arguments.allow_execute:
        parser.error("real host execution requires --allow-execute")
    if not 1 <= arguments.samples <= 3 or not math.isfinite(arguments.timeout_seconds) \
            or not 0 < arguments.timeout_seconds <= 600:
        parser.error("samples must be 1..3 and total timeout must be in (0, 600]")
    policy = arguments.policy.read_text()
    deadline = time.monotonic() + arguments.timeout_seconds
    results = []
    for _ in range(arguments.samples):
        with tempfile.TemporaryDirectory(prefix="converge-interaction-") as directory:
            session = CodexSession(directory, policy, codex_bin=arguments.codex_bin,
                                   model=arguments.model, deadline=deadline)
            result = replay(arguments.case, Path(directory), session, controlled=arguments.controlled)
            result["evidence_level"] = "host_observed" if session.started else "uncovered"
            results.append(result)
        if result["result"] == "uncovered":
            break
    report = {"policy_fingerprint": hashlib.sha256(policy.encode()).hexdigest(),
              "model": arguments.model, "requested_samples": arguments.samples, "samples": results,
              "release_status": "uncovered"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    expected = "blocked" if arguments.case == "no-progress" and arguments.controlled else "pass"
    return 0 if len(results) == arguments.samples and all(x["result"] == expected for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
