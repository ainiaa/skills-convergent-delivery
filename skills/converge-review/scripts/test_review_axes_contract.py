#!/usr/bin/env python3
"""Contract tests for bounded, axis-isolated review orchestration."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills/converge-review/SKILL.md"
CONTRACT = ROOT / "skills/converge-review/references/review-contract.md"
ORCHESTRATION = ROOT / "references/review-orchestration.md"
ROOT_SKILL = ROOT / "SKILL.md"


class ReviewAxesContractTest(unittest.TestCase):
    def setUp(self):
        self.skill = SKILL.read_text(encoding="utf-8")
        self.contract = CONTRACT.read_text(encoding="utf-8")
        self.orchestration = ORCHESTRATION.read_text(encoding="utf-8")
        self.root_skill = ROOT_SKILL.read_text(encoding="utf-8")

    def test_root_controller_enforces_mandatory_axes_in_order(self):
        for marker in (
            "每个 task 必须依次通过 `spec -> quality`",
            "每轴最多一次 repair 和一次 re-review",
            "全部 task 的两个 mandatory 轴",
            "高风险可追加新鲜 `blind` 审查，但不得替代",
        ):
            self.assertIn(marker, self.root_skill)

    def test_task_review_keeps_spec_before_quality_and_results_separate(self):
        self.assertIn("Review Protocol v2", self.contract)
        self.assertIn('"axis": "spec | quality | integration"', self.contract)
        self.assertIn("spec -> quality", self.orchestration)
        self.assertIn("不得合并、覆盖或相互抵消", self.orchestration)

    def test_each_axis_has_one_repair_and_one_re_review_budget(self):
        self.assertIn('"repair_budget": 1', self.orchestration)
        self.assertIn('"re_review_budget": 1', self.orchestration)
        self.assertIn("相同 finding 指纹", self.orchestration)
        self.assertIn("source_fingerprint 未变化", self.orchestration)
        self.assertIn('"status": "blocked"', self.orchestration)

    def test_integration_review_runs_after_tasks_and_only_for_cross_task_risk(self):
        self.assertIn("全部任务的 spec 与 quality", self.orchestration)
        self.assertIn("只审查跨任务风险", self.orchestration)
        self.assertIn("task-local", self.contract)
        self.assertIn('"axis": "integration"', self.skill)

    def test_quality_and_integration_preserve_independence_and_freshness(self):
        self.assertIn("quality 与 integration 初审必须使用 `blind` 和全新上下文", self.contract)
        self.assertIn("源码变化后旧结果立即 stale", self.contract)

    def test_legacy_intent_blind_and_closure_requests_remain_readable(self):
        self.assertIn("protocol_version=1", self.contract)
        self.assertIn("intent", self.contract)
        self.assertIn("blind", self.contract)
        self.assertIn("closure", self.contract)
        self.assertIn("不得推断 axis", self.contract)


if __name__ == "__main__":
    unittest.main()
