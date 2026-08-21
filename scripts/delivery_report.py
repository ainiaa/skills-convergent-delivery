#!/usr/bin/env python3
"""Render a deterministic user receipt from a validated Converge state."""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from delivery_next import normalize_open_issues, upgrade_state, validate_state


NO_NEXT_ACTION = {"", "none", "no", "n/a", "无", "没有", "无需行动"}
TITLES = {
    "ready": "已完成，可使用",
    "attention": "已完成，需关注",
    "decision": "需你确认",
    "blocked": "暂时无法继续",
}


def build_report(state):
    state = upgrade_state(state)
    validate_state(state, SimpleNamespace())
    acceptance = state["ledger"]["acceptance"]
    pending_acceptance = sum(
        item["result"] != "pass" or item["freshness"] != "fresh" for item in acceptance
    )
    open_issues = normalize_open_issues(state["handoff"]["open_issues"])
    pending_items = max(pending_acceptance, len(open_issues))

    if state["status"] == "blocked":
        outcome = "decision" if state.get("blocked_code") == "decision" else "blocked"
    elif state["status"] == "complete":
        outcome = "attention" if pending_items else "ready"
    else:
        outcome = "attention"

    return {
        "outcome": outcome,
        "title": TITLES[outcome],
        "goal": state["handoff"]["goal"],
        "verification": state["handoff"]["last_verification"],
        "completed_rounds": state["ledger"]["completed_rounds"],
        "repaired_issues": len(state["ledger"]["repair_fingerprints"]),
        "key_changes": state["ledger"].get("key_changes", []),
        "pending_items": pending_items,
        "acceptance": [
            {
                "criterion": item["criterion"],
                "result": item["result"],
                "freshness": item["freshness"],
            }
            for item in acceptance
        ],
        "reason": state.get("blocked_reason") or "；".join(open_issues),
        "open_issues": open_issues,
        "next_action": state["handoff"]["next_action"],
    }


def build_diagnostic(state):
    upgraded = upgrade_state(state)
    binding = upgraded["provider_binding"]["binding"]
    return {
        "status": upgraded["status"],
        "current_stage": upgraded["current_stage"],
        "controller_protocol": upgraded["controller"]["protocol_version"],
        "workflow_provider": binding["workflow_provider"]["id"],
        "stage_providers": {
            stage: provider["id"] for stage, provider in binding["stage_providers"].items()
        },
        "workers": [
            {"ref": worker["ref"], "status": worker["status"]}
            for worker in upgraded["workers"]
        ],
        "checks": upgraded["ledger"]["checks"],
    }


def render_text(report, detail=False):
    lines = [
        f"结果：{report['title']}：{report['goal']}",
    ]
    if report["key_changes"]:
        lines.append(f"关键改动：{'；'.join(report['key_changes'])}")
    lines.extend([
        f"已验证：{report['verification']}",
        "过程："
        f"{report['completed_rounds']} 个交付轮；"
        f"修复 {report['repaired_issues']} 个问题；"
        f"待处理 {report['pending_items']} 项",
    ])
    if report["outcome"] != "ready" and report["reason"]:
        lines.append(f"未验证/影响：{report['reason']}")
    if report["next_action"].strip().lower() not in NO_NEXT_ACTION:
        lines.append(f"下一步：{report['next_action']}")
    if detail or report["outcome"] in {"blocked", "decision"}:
        diagnostic = report.get("diagnostic", {})
        workers = diagnostic.get("workers", [])
        checks = diagnostic.get("checks", [])
        worker_summary = ", ".join(
            f"{str(worker.get('ref', '?'))[:60]}={worker.get('status', '?')}"
            for worker in workers[:5]
        ) or "none"
        check_summary = ", ".join(
            f"{str(check.get('command', '?'))[:80]}={check.get('result', '?')}"
            for check in checks[:5]
        ) or "none"
        lines.extend([
            "技术诊断：",
            f"Provider：{diagnostic.get('workflow_provider', '由已验证状态确定')}；"
            f"阶段：{diagnostic.get('current_stage', '已验证')}；"
            f"交付轮 {report['completed_rounds']}；修复 {report['repaired_issues']}",
            f"Workers：{worker_summary}{f'；另有 {len(workers) - 5} 个' if len(workers) > 5 else ''}",
            f"Checks：{check_summary}{f'；另有 {len(checks) - 5} 项' if len(checks) > 5 else ''}",
        ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--state")
    source.add_argument("--input", choices=("-",))
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--detail", action="store_true")
    arguments = parser.parse_args()
    try:
        state = json.load(sys.stdin) if arguments.input == "-" else json.loads(
            Path(arguments.state).read_text(encoding="utf-8")
        )
        report = build_report(state)
        if arguments.detail or report["outcome"] in {"blocked", "decision"}:
            report["diagnostic"] = build_diagnostic(state)
        if arguments.format == "json":
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            print(render_text(report, arguments.detail))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"report blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
