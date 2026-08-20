#!/usr/bin/env python3
"""Render a deterministic user receipt from a validated Converge state."""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from delivery_next import validate_state


NO_OPEN_ISSUES = {"", "none", "no", "n/a", "无", "没有", "无需处理"}
NO_NEXT_ACTION = {"", "none", "no", "n/a", "无", "没有", "无需行动"}
TITLES = {
    "ready": "已完成，可使用",
    "attention": "已完成，需关注",
    "decision": "需你确认",
    "blocked": "暂时无法继续",
}


def has_open_issues(value):
    return value.strip().lower() not in NO_OPEN_ISSUES


def build_report(state):
    validate_state(state, SimpleNamespace())
    acceptance = state["ledger"]["acceptance"]
    pending_acceptance = sum(
        item["result"] != "pass" or item["freshness"] != "fresh" for item in acceptance
    )
    open_issue = has_open_issues(state["handoff"]["open_issues"])
    pending_items = max(pending_acceptance, int(open_issue))

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
        "pending_items": pending_items,
        "acceptance": [
            {
                "criterion": item["criterion"],
                "result": item["result"],
                "freshness": item["freshness"],
            }
            for item in acceptance
        ],
        "reason": state.get("blocked_reason") or state["handoff"]["open_issues"],
        "open_issues": state["handoff"]["open_issues"],
        "next_action": state["handoff"]["next_action"],
    }


def render_text(report):
    lines = [
        f"结果：{report['title']}：{report['goal']}",
        f"已验证：{report['verification']}",
        "过程："
        f"{report['completed_rounds']} 个交付轮；"
        f"修复 {report['repaired_issues']} 个问题；"
        f"待处理 {report['pending_items']} 项",
    ]
    if report["outcome"] != "ready" and has_open_issues(report["reason"]):
        lines.append(f"未验证/影响：{report['reason']}")
    if report["next_action"].strip().lower() not in NO_NEXT_ACTION:
        lines.append(f"下一步：{report['next_action']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    arguments = parser.parse_args()
    try:
        state = json.loads(Path(arguments.state).read_text(encoding="utf-8"))
        report = build_report(state)
        if arguments.format == "json":
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            print(render_text(report))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"report blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
