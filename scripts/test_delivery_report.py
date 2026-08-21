import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from delivery_next import upgrade_state
from runtime_adapter import cleanup_receipt, negotiate


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/delivery_report.py"


def state(status="complete"):
    result = {
        "schema_version": 5,
        "run_id": "run-1",
        "repo_id": "/repo/.git",
        "task_key": "task-1",
        "writer_id": "writer-1",
        "revision": 3,
        "workspace": "/repo/worktree",
        "baseline": {"commit": "abc123", "diff_fingerprint": "clean"},
        "scope_fingerprint": "scope-1",
        "source_fingerprint": "a" * 64,
        "execution_control": {
            "routing": {
                "schema_version": 1, "status": "frozen", "assessment_count": 1,
                "route": "inline", "review_tier": "low", "profile_fingerprint": "b" * 64,
            },
            "review": {
                "protocol_version": 2, "source_fingerprint": "a" * 64,
                "repair_budget_remaining": 1, "re_review_budget_remaining": 1,
                "integration_budget_remaining": 0, "requests": [],
            },
        },
        "engine": {"name": "native-v1", "selection": "auto", "reason": "fallback"},
        "current_stage": "verify-final",
        "requires_stability_round": False,
        "status": status,
        "ledger": {
            "completed_rounds": 2,
            "repair_fingerprints": ["issue-a", "issue-b"],
            "key_changes": ["统一 Provider 契约", "增加可见进度"],
            "checks": [{"stage": "final", "command": "check", "result": "pass"}],
            "acceptance": [
                {
                    "criterion": "doctor detects incomplete Suite",
                    "evidence": "test_install",
                    "result": "pass",
                    "freshness": "fresh",
                    "source_fingerprint": "a" * 64,
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
            "open_issues": "无",
            "next_action": "无需行动",
        },
    }
    if status == "blocked":
        result["blocked_code"] = "environment"
        result["blocked_reason"] = "runtime unavailable"
        result["ledger"]["acceptance"][0].update(result="unknown", freshness="unavailable")
        result["handoff"]["open_issues"] = "runtime unavailable"
    return result


class DeliveryReportTest(unittest.TestCase):
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
            payload["workspace_changes"] = {
                "file_count": 999,
                "lines_added": 999,
                "lines_deleted": 999,
                "binary_file_count": 999,
            }

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

        result = self.run_report(payload, "json")

        self.assertEqual(0, result.returncode, result.stderr)
        summary = json.loads(result.stdout)["workspace_changes"]
        self.assertEqual("unavailable", summary["status"])
        self.assertEqual("git_read_failed", summary["error"])

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
        payload["runtime_binding"] = negotiate(
            "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                      "tree_query": True, "restrict_dispatch": False}
        )
        payload["workers"] = [{
            "ref": "worker-1", "parent_ref": None, "task_id": payload["task_key"],
            "depth": 1, "may_dispatch": False, "role": "reviewer",
            "owner_run_id": payload["run_id"], "status": "working", "progress": None,
        }]
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], payload["revision"], ["worker-1"],
            ["worker-1"], ["unexpected-1"], "2026-08-21T00:00:00Z",
        )

        report = json.loads(self.run_report(payload, "json").stdout)

        self.assertEqual(["worker-1"], report["diagnostic"]["cleanup"]["active_refs"])
        self.assertEqual(["unexpected-1"], report["diagnostic"]["cleanup"]["unexpected_refs"])

    def test_text_diagnostic_includes_bounded_worker_and_check_summaries(self):
        payload = upgrade_state(state())
        payload["workers"] = [{
            "ref": "worker-1",
            "parent_ref": None,
            "task_id": "task-1",
            "depth": 1,
            "may_dispatch": False,
            "role": "review",
            "owner_run_id": "run-1",
            "status": "completed",
            "progress": None,
        }]
        payload["runtime_binding"] = negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )
        payload["worker_tree_receipt"] = cleanup_receipt(
            payload["runtime_binding"], 3, ["worker-1"], [], [],
            "2026-08-21T00:00:00Z",
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

    def test_legacy_no_issue_text_is_not_reported_as_pending(self):
        for value in ("No remaining scoped findings", "0"):
            with self.subTest(value=value):
                payload = state()
                payload["handoff"]["open_issues"] = value

                report = json.loads(self.run_report(payload).stdout)

                self.assertEqual("ready", report["outcome"])
                self.assertEqual(0, report["pending_items"])

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

    def test_blocked_report_is_not_ready(self):
        result = self.run_report(state("blocked"), "text")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("暂时无法继续", result.stdout)
        self.assertIn("runtime unavailable", result.stdout)
        self.assertIn("待处理 1 项", result.stdout)
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
