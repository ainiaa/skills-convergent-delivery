#!/usr/bin/env python3
"""Render a deterministic user receipt from a validated Converge state."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from delivery_next import normalize_open_issues, upgrade_state, validate_state
from delivery_progress import render_workspace_change_summary, workspace_change_summary
from evidence_contract import valid_evidence_receipts


NO_NEXT_ACTION = {"", "none", "no", "n/a", "无", "没有", "无需行动"}
TITLES = {
    "ready": "已完成，可使用",
    "attention": "已完成，需关注",
    "decision": "需你确认",
    "blocked": "暂时无法继续",
}


def execution_metrics(state):
    token_values = []
    for result in state["ledger"].get("runner_results", []):
        usage = result.get("usage")
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            token_values.append(total)
    total_tokens = (
        {"status": "available", "value": sum(token_values), "source": "signed_runner_receipts"}
        if token_values else
        {"status": "unavailable", "reason": "no_signed_total_token_usage"}
    )
    unavailable = {
        "status": "unavailable",
        "reason": "current_host_does_not_expose_signed_usage",
    }
    return {
        "total_tokens": total_tokens,
        "tool_calls": dict(unavailable),
        "user_blocks": dict(unavailable),
    }


def build_report(state):
    validate_state(state, SimpleNamespace(strict_evidence=True))
    state = upgrade_state(state)
    acceptance = state["ledger"]["acceptance"]
    pending_acceptance = sum(
        item["result"] != "pass" or item["freshness"] != "fresh" for item in acceptance
    )
    open_issues = normalize_open_issues(state["handoff"]["open_issues"])
    open_issue_count = len(open_issues)
    workspace_changes = workspace_change_summary(state)
    pending_items = pending_acceptance + open_issue_count
    verification_scope = {
        "acceptance": [
            {"criterion": item["criterion"], "evidence": item["evidence"]}
            for item in acceptance
            if item["result"] == "pass" and item["freshness"] == "fresh"
        ],
        "checks": [
            {"stage": item["stage"], "command": item["command"]}
            for item in state["ledger"]["checks"]
            if item["result"] == "pass" and valid_evidence_receipts(
                item.get("evidence_receipts"), state.get("source_receipt")
            )
        ],
    }
    verification_evidence_levels = sorted({
        receipt["evidence_level"]
        for item in acceptance
        if item["result"] == "pass" and item["freshness"] == "fresh"
        for receipt in item.get("evidence_receipts", [])
    })
    attested_check_count = sum(
        item["result"] == "pass" and not valid_evidence_receipts(
            item.get("evidence_receipts"), state.get("source_receipt")
        )
        for item in state["ledger"]["checks"]
    )
    verification_parts = []
    if verification_scope["acceptance"]:
        verification_parts.append(
            "验收：" + "、".join(
                item["criterion"] for item in verification_scope["acceptance"]
            )
        )
    if verification_scope["checks"]:
        verification_parts.append(
            "检查：" + "、".join(item["command"] for item in verification_scope["checks"])
        )

    if state["status"] == "blocked":
        outcome = "decision" if state.get("blocked_code") == "decision" else "blocked"
    elif state["status"] == "complete":
        outcome = "attention" if pending_items or workspace_changes["status"] != "available" else "ready"
    else:
        outcome = "attention"

    report = {
        "outcome": outcome,
        "title": TITLES[outcome],
        "goal": state["handoff"]["goal"],
        "verification": "；".join(verification_parts) or "无结构化验证证据",
        "verification_scope": verification_scope,
        "verification_evidence_levels": verification_evidence_levels,
        "attested_check_count": attested_check_count,
        "verification_note": state["handoff"]["last_verification"],
        "verification_note_level": "controller_attested",
        "completed_rounds": state["ledger"]["completed_rounds"],
        "repaired_issues": len(state["ledger"]["repair_fingerprints"]),
        "key_changes": state["ledger"].get("key_changes", []),
        "pending_items": pending_items,
        "pending_acceptance": pending_acceptance,
        "open_issue_count": open_issue_count,
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
        "workspace_changes": workspace_changes,
        "execution_metrics": execution_metrics(state),
    }
    identity = {
        key: report[key]
        for key in (
            "outcome", "goal", "verification", "verification_scope", "verification_note",
            "verification_evidence_levels", "attested_check_count",
            "verification_note_level", "completed_rounds", "repaired_issues",
            "key_changes", "pending_acceptance", "open_issues", "workspace_changes",
            "execution_metrics",
        )
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    previous = state["ledger"].get("report_history") or {}
    report["unchanged"] = previous.get("summary_fingerprint") == fingerprint
    report["next_report_history"] = {
        "last_outcome": outcome,
        "reported_fingerprints": sorted(set(
            state["ledger"]["repair_fingerprints"] + open_issues
        )),
        "summary_fingerprint": fingerprint,
    }
    return report


def build_diagnostic(state):
    upgraded = upgrade_state(state)
    binding = upgraded["provider_binding"]["binding"]
    cleanup = upgraded.get("worker_tree_receipt") or {}
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
        "cleanup": {
            "active_refs": cleanup.get("active_refs", []),
            "unexpected_refs": cleanup.get("unexpected_refs", []),
        },
        "checks": upgraded["ledger"]["checks"],
    }


def render_text(report, detail=False):
    if report["unchanged"] and not detail:
        return "\n".join([
            f"结果：无新增变化：{report['title']}",
            f"已验证范围：{report['verification']}",
            "证据等级：" + ("、".join(report["verification_evidence_levels"]) or "无"),
            f"说明（{report['verification_note_level']}）：{report['verification_note']}",
            "待处理："
            f"验收未通过 {report['pending_acceptance']} 项；"
            f"其他待处理 {report['open_issue_count']} 项",
        ])
    lines = [
        f"结果：{report['title']}：{report['goal']}",
    ]
    if report["key_changes"]:
        lines.append(f"关键改动：{'；'.join(report['key_changes'])}")
    lines.append(render_workspace_change_summary(report["workspace_changes"]))
    lines.extend([
        f"已验证范围：{report['verification']}",
        "证据等级：" + ("、".join(report["verification_evidence_levels"]) or "无")
        + (f"；另有 {report['attested_check_count']} 项控制器记录未计入验证"
           if report["attested_check_count"] else ""),
        f"说明（{report['verification_note_level']}）：{report['verification_note']}",
        "过程："
        f"{report['completed_rounds']} 个交付轮；"
        f"修复 {report['repaired_issues']} 个问题",
        "待处理："
        f"验收未通过 {report['pending_acceptance']} 项；"
        f"其他待处理 {report['open_issue_count']} 项",
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
