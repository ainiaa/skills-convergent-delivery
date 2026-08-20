import json
import subprocess
import tempfile
import unittest
from pathlib import Path


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
    def run_report(self, payload, output_format="json"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                ["python3", str(SCRIPT), "--state", str(path), "--format", output_format],
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
