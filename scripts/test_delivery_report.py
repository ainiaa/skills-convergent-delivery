import json
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from delivery_engine import controller_identity, provider_reference
from delivery_next import upgrade_state
from evidence_contract import run_evidence, workspace_source
from runtime_adapter import _bind, cleanup_receipt
from task_profile import freeze_routing
from provider_contract import canonical_fingerprint
from role_result import result_from_output
from runner_contract import bind_role_result, fingerprint as runner_fingerprint, freeze_launch
from test_delivery_next import tdd_trace
from worker_profile import fingerprint as worker_profile_fingerprint


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/delivery_report.py"
HEAD = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
    capture_output=True, text=True,
).stdout.strip()
SOURCE = workspace_source(ROOT, HEAD)
EVIDENCE = run_evidence(ROOT, HEAD, [sys.executable, "-c", "pass"])


def legacy_runtime_binding(query_id, capabilities):
    observation = {
        "query_id": query_id, "observed_at": "2026-08-21T00:00:00Z",
        "profile": "codex", "capabilities": capabilities,
    }
    return _bind("codex", "automatic", capabilities, "legacy test fixture",
                 "host_observed", observation)


def cleanup_receipt(binding, revision, registered_refs, active_refs, unexpected_refs, observed_at,
                    host_observation=None):
    return {
        "schema_version": 2, "observed_revision": revision, "observed_at": observed_at,
        "runtime_fingerprint": binding["binding_fingerprint"], "mode": "tree_query",
        "evidence_level": "host_observed", "observation_fingerprint": "a" * 64,
        "registered_refs": registered_refs, "active_refs": active_refs,
        "unexpected_refs": unexpected_refs,
    }


def routing():
    return freeze_routing({
        "schema_version": 2, "assessment_phase": "frozen", "scope": "local",
        "coupling": "single", "uncertainty": "low", "verification": "local",
        "risk_flags": [], "cross_session": False, "delegable_tasks": 0,
        "context_isolation_benefit": False,
    }, ["."])


def state(status="complete"):
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference("native-v1", "feature"),
        "stage_providers": {},
    }
    result = {
        "schema_version": 10,
        "run_id": "run-1",
        "repo_id": str(ROOT / ".git"),
        "task_key": "task-1",
        "writer_id": "writer-1",
        "revision": 3,
        "workspace": str(ROOT),
        "baseline": {"commit": HEAD, "diff_fingerprint": "clean"},
        "scope_fingerprint": "scope-1",
        "source_fingerprint": SOURCE["source_fingerprint"],
        "source_receipt": SOURCE,
        "execution_control": {
            "routing": routing(),
            "review": {
                "protocol_version": 3,
                "repair_budget_remaining": 1, "re_review_budget_remaining": 1,
                "integration_budget_remaining": 0,
                "rounds": [{"source_fingerprint": SOURCE["source_fingerprint"], "requests": []}],
            },
        },
        "controller": controller_identity(),
        "provider_binding": {
            "selection": "auto", "reason": "fallback", "task_kind": "feature",
            "binding": binding, "binding_fingerprint": canonical_fingerprint(binding),
        },
        "current_stage": "verify-final",
        "requires_stability_round": False,
        "status": status,
        "ledger": {
            "completed_rounds": 2,
            "repair_fingerprints": ["issue-a", "issue-b"],
            "tdd_trace": tdd_trace(SOURCE, criterion="doctor detects incomplete Suite"),
            "key_changes": ["统一 Provider 契约", "增加可见进度"],
            "checks": [{"stage": "final", "command": "check", "result": "pass"}],
            "acceptance": [
                {
                    "criterion": "doctor detects incomplete Suite",
                    "evidence": "test_install",
                    "result": "pass",
                    "freshness": "fresh",
                    "source_fingerprint": SOURCE["source_fingerprint"],
                    "evidence_receipts": [copy.deepcopy(EVIDENCE)],
                }
            ],
            "report_history": {
                "last_outcome": "ready",
                "reported_fingerprints": [],
                "summary_fingerprint": "none",
            },
        },
        "handoff": {
            "goal": "harden converge runtime",
            "last_verification": "all checks passed",
            "open_issues": [],
            "next_action": "无需行动",
        },
        "workers": [], "worker_tree_receipt": None, "runtime_binding": None,
        "host_sync": {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        },
    }
    if status == "blocked":
        result["blocked_code"] = "environment"
        result["blocked_reason"] = "runtime unavailable"
        result["ledger"]["acceptance"][0].update(result="unknown", freshness="unavailable")
        result["handoff"]["open_issues"] = ["runtime unavailable"]
    return upgrade_state(result)


class DeliveryReportTest(unittest.TestCase):
    def test_json_reports_only_usage_present_in_fingerprint_validated_runner_receipts(self):
        payload = state()
        profile = {
            "schema_version": 1, "worker_id": "scout-1", "role": "scout",
            "runner_id": "openai-compatible-v1",
            "requested": {"model": "glm-5.2", "reasoning_effort": "low"},
            "effective": {"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "low"},
            "permissions": {"workspace": "read", "shell": False, "network": "egress"},
            "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 1000},
        }
        profile["profile_fingerprint"] = worker_profile_fingerprint(profile)
        launch = freeze_launch(profile, "review", {"api_key_env": "GLM_API_KEY"})
        result = {
            "schema_version": 1, "runner_id": "openai-compatible-v1",
            "launch_fingerprint": launch["launch_fingerprint"], "status": "completed",
            "response_id": "request-1", "response_model": "glm-5.2",
            "usage": {"total_tokens": 12}, "response_fingerprint": "a" * 64,
        }
        result["receipt_fingerprint"] = runner_fingerprint(result)
        result = bind_role_result(launch, result, result_from_output(launch, {
            "status": "available",
            "content": '{"findings":[{"summary":"usage reported","evidence":[{"kind":"artifact","reference":"provider-receipt.json","content_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}],"next_action":"continue"}',
        }))
        payload["ledger"].update(runner_launches=[launch], runner_results=[result])

        report = json.loads(self.run_report(payload, "json").stdout)

        self.assertEqual(
            {"status": "available", "value": 12, "source": "fingerprint_validated_runner_receipts"},
            report["execution_metrics"]["total_tokens"],
        )
        self.assertEqual("unavailable", report["execution_metrics"]["tool_calls"]["status"])
        self.assertEqual("unavailable", report["execution_metrics"]["user_blocks"]["status"])

    def test_final_report_uses_parent_git_summary_and_dirty_baseline_note(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.name", "Test"], check=True
            )
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.email", "test@example.com"],
                check=True,
            )
            (workspace / "tracked.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace), "add", "tracked.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "commit", "-q", "-m", "seed"], check=True
            )
            (workspace / "tracked.txt").write_text("new\n", encoding="utf-8")
            (workspace / "untracked.txt").write_text("one\ntwo\n", encoding="utf-8")
            (workspace / "untracked.bin").write_bytes(b"\0binary")
            payload = state()
            payload["workspace"] = str(workspace)
            payload["repo_id"] = str(workspace / ".git")
            payload["baseline"]["commit"] = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            payload["baseline"]["diff_fingerprint"] = "dirty-at-start"
            payload.pop("source_receipt")
            payload["ledger"]["acceptance"][0].pop("evidence_receipts")
            payload.update(status="active", current_stage="round-1-semantic-review")

            report = json.loads(self.run_report(payload, "json").stdout)
            rendered = self.run_report(payload, "text").stdout

            self.assertEqual(
                {
                    "status": "available",
                    "file_count": 3,
                    "lines_added": 3,
                    "lines_deleted": 1,
                    "binary_file_count": 1,
                    "baseline_note": "统计包含任务开始前已有改动，不能归因于本任务",
                    "error": None,
                },
                report["workspace_changes"],
            )
            self.assertIn("工作区累计：3 files，+3/-1，1 binary", rendered)
            self.assertIn("统计包含任务开始前已有改动，不能归因于本任务", rendered)
            self.assertNotIn("999", rendered)

    def test_final_report_degrades_structurally_when_git_is_unavailable(self):
        payload = state()
        payload["workspace"] = "/missing/worktree"
        payload.pop("source_receipt")
        payload["ledger"]["acceptance"][0].pop("evidence_receipts")
        payload.update(status="active", current_stage="round-1-semantic-review")

        result = self.run_report(payload, "json")

        self.assertEqual(0, result.returncode, result.stderr)
        summary = json.loads(result.stdout)["workspace_changes"]
        self.assertEqual("unavailable", summary["status"])
        self.assertEqual("git_read_failed", summary["error"])
        self.assertEqual("attention", json.loads(result.stdout)["outcome"])

    def test_default_report_hides_diagnostics_but_detail_includes_them(self):
        summary = self.run_report(state(), "text")
        detailed = self.run_report(state(), "text", detail=True)

        self.assertNotIn("技术诊断", summary.stdout)
        self.assertNotIn("provider_binding", summary.stdout)
        self.assertIn("技术诊断", detailed.stdout)
        self.assertIn("Provider", detailed.stdout)

        summary_json = json.loads(self.run_report(state(), "json").stdout)
        detail_json = json.loads(self.run_report(state(), "json", detail=True).stdout)
        self.assertNotIn("diagnostic", summary_json)
        self.assertEqual("native-v1", detail_json["diagnostic"]["workflow_provider"])

    def test_blocked_json_includes_diagnostics_without_detail_flag(self):
        payload = json.loads(self.run_report(state("blocked"), "json").stdout)

        self.assertIn("diagnostic", payload)
        self.assertEqual("blocked", payload["diagnostic"]["status"])

    def test_blocked_diagnostic_reports_active_and_unexpected_cleanup_refs(self):
        payload = upgrade_state(state("blocked"))
        payload["execution_control"]["routing"] = freeze_routing(
            {
                **payload["execution_control"]["routing"]["profile"],
                "scope": "cross-module",
                "coupling": "independent", "delegable_tasks": 1,
                "context_isolation_benefit": True,
            }, ["."],
        )
        payload["runtime_binding"] = legacy_runtime_binding(
            "capabilities-report", ["dispatch", "query", "wait", "interrupt", "tree_query"]
        )
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "pdlc",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], payload["revision"], ["worker-1"],
            ["worker-1"], ["unexpected-1"], "2026-08-21T00:00:00Z",
            host_observation={
                "query_id": "query-report", "observed_at": "2026-08-21T00:00:00Z",
                "registered_refs": ["worker-1"], "active_refs": ["worker-1"],
                "unexpected_refs": ["unexpected-1"],
            },
        )

        report = json.loads(self.run_report(payload, "json").stdout)

        self.assertEqual(["worker-1"], report["diagnostic"]["cleanup"]["active_refs"])
        self.assertEqual(["unexpected-1"], report["diagnostic"]["cleanup"]["unexpected_refs"])

    def test_text_diagnostic_includes_bounded_worker_and_check_summaries(self):
        payload = upgrade_state(state("blocked"))
        payload.update(blocked_code="environment", blocked_reason="legacy worker diagnostic")
        payload["execution_control"]["routing"] = freeze_routing(
            {
                **payload["execution_control"]["routing"]["profile"],
                "coupling": "independent", "delegable_tasks": 1,
                "context_isolation_benefit": True,
            }, ["."],
        )
        payload["workers"] = [{
            "ref": "worker-1",
            "parent_ref": None,
            "task_id": "task-1",
            "depth": 1,
            "may_dispatch": False,
            "role": "pdlc",
            "owner_run_id": "run-1",
            "status": "completed",
            "progress": None,
        }]
        payload["runtime_binding"] = legacy_runtime_binding(
            "capabilities-detail", ["dispatch", "query", "tree_query"]
        )
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, ["worker-1"], [], [],
            "2026-08-21T00:00:00Z",
            host_observation={
                "query_id": "query-detail", "observed_at": "2026-08-21T00:00:00Z",
                "registered_refs": ["worker-1"], "active_refs": [],
                "unexpected_refs": [],
            },
        )

        result = self.run_report(payload, "text", detail=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("worker-1=completed", result.stdout)
        self.assertIn("check=pass", result.stdout)

    def run_report(self, payload, output_format="json", detail=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            command = ["python3", str(SCRIPT), "--state", str(path), "--format", output_format]
            if detail:
                command.append("--detail")
            return subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_ready_report_has_deterministic_counts(self):
        result = self.run_report(state())

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("ready", report["outcome"])
        self.assertEqual(2, report["completed_rounds"])
        self.assertEqual(2, report["repaired_issues"])
        self.assertEqual(0, report["pending_items"])
        self.assertEqual("pass", report["acceptance"][0]["result"])
        self.assertEqual(["统一 Provider 契约", "增加可见进度"], report["key_changes"])
        self.assertEqual(["observed"], report["verification_evidence_levels"])
        self.assertEqual([], report["verification_scope"]["checks"])

    def test_autonomous_completion_report_includes_only_the_current_audit_receipt_summary(self):
        from test_autonomy_gate import completed_state

        result = self.run_report(completed_state())

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            {
                "status": "pass",
                "source_fingerprint": SOURCE["source_fingerprint"],
                "covered_manifest_ids": ["requirement", "scope", "acceptance"],
            },
            report["autonomy_audit"],
        )

    def test_report_does_not_launder_controller_attested_acceptance_as_ready(self):
        payload = state()
        payload["ledger"]["acceptance"][0]["evidence_receipts"][0][
            "evidence_level"
        ] = "controller_attested"

        result = self.run_report(payload)

        self.assertEqual(2, result.returncode)
        self.assertIn("Evidence Receipt", result.stderr)

    def test_legacy_open_issue_text_is_rejected(self):
        for value in ("No remaining scoped findings", "0"):
            with self.subTest(value=value):
                payload = state()
                payload["handoff"]["open_issues"] = value

                result = self.run_report(payload)
                self.assertEqual(2, result.returncode)
                self.assertIn("open_issues", result.stderr)

    def test_structured_open_issues_preserve_the_exact_item_count(self):
        payload = state()
        payload["handoff"]["open_issues"] = ["first issue", "second issue"]

        result = self.run_report(payload)

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("attention", report["outcome"])
        self.assertEqual(2, report["pending_items"])

    def test_ready_text_leads_with_useful_changes_without_internal_terms(self):
        result = self.run_report(state(), "text")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("关键改动：统一 Provider 契约；增加可见进度", result.stdout)
        self.assertNotIn("lease", result.stdout)
        self.assertNotIn("fingerprint", result.stdout)

    def test_handoff_verification_text_is_labeled_as_attested_not_verified(self):
        payload = state()
        payload["handoff"]["last_verification"] = "production is fully verified"

        report = json.loads(self.run_report(payload, "json").stdout)
        rendered = self.run_report(payload, "text").stdout

        self.assertEqual(
            "验收：doctor detects incomplete Suite",
            report["verification"],
        )
        self.assertEqual(1, report["attested_check_count"])
        self.assertEqual("controller_attested", report["verification_note_level"])
        self.assertIn("已验证范围：验收：doctor detects incomplete Suite", rendered)
        self.assertIn("1 项控制器记录未计入验证", rendered)
        self.assertIn("说明（controller_attested）：production is fully verified", rendered)
        self.assertNotIn("已验证：production is fully verified", rendered)

    def test_blocked_report_is_not_ready(self):
        result = self.run_report(state("blocked"), "text")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("暂时无法继续", result.stdout)
        self.assertIn("runtime unavailable", result.stdout)
        self.assertIn("验收未通过 1 项；其他待处理 1 项", result.stdout)
        self.assertNotIn("已完成，可使用", result.stdout)

    def test_ready_text_omits_a_noop_next_step(self):
        result = self.run_report(state(), "text")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("下一步：无需行动", result.stdout)

    def test_invalid_state_is_rejected(self):
        payload = state()
        payload["ledger"]["completed_rounds"] = 9

        result = self.run_report(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("report blocked", result.stderr)

    def test_handoff_text_is_bounded(self):
        payload = state()
        payload["handoff"]["goal"] = "x" * 501

        result = self.run_report(payload)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("handoff.goal", result.stderr)

    def test_repeated_report_is_marked_unchanged(self):
        first = json.loads(self.run_report(state()).stdout)
        payload = state()
        payload["ledger"]["report_history"] = first["next_report_history"]

        repeated = json.loads(self.run_report(payload).stdout)
        rendered = self.run_report(payload, "text").stdout

        self.assertTrue(repeated["unchanged"])
        self.assertIn("无新增变化", rendered)

    def test_stdin_input_matches_state_file_without_a_lease(self):
        payload = state()
        from_state = self.run_report(payload)
        from_stdin = subprocess.run(
            ["python3", str(SCRIPT), "--input", "-", "--format", "json"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, from_stdin.returncode, from_stdin.stderr)
        self.assertEqual(from_state.stdout, from_stdin.stdout)


if __name__ == "__main__":
    unittest.main()
