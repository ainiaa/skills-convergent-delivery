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

    def test_root_controller_routes_review_by_risk(self):
        self.assertIn("[审查编排](references/review-orchestration.md)", self.root_skill)
        for marker in (
            "低风险任务",
            "fresh reviewer",
            "高风险任务使用一个 blind reviewer",
            "多任务或跨服务计划",
            "一次 repair 和一次定向 re-review",
        ):
            self.assertIn(marker, self.orchestration)

    def test_task_review_keeps_spec_before_quality_and_results_separate(self):
        self.assertIn("Review Protocol v3", self.contract)
        self.assertIn('"axis": "spec | quality | integration"', self.contract)
        self.assertIn("需求符合性与实现质量仍分别保存结论", self.orchestration)
        self.assertIn("两个有序单轴请求", self.orchestration)
        self.assertNotIn("一次请求中返回两轴", self.orchestration)

    def test_each_axis_has_one_repair_and_one_re_review_budget(self):
        self.assertIn('"repair_budget": 1', self.orchestration)
        self.assertIn('"re_review_budget": 1', self.orchestration)
        self.assertIn("相同 finding 指纹", self.orchestration)
        self.assertIn("source_fingerprint 未变化", self.orchestration)
        self.assertIn('"status": "blocked"', self.orchestration)

    def test_integration_review_runs_after_tasks_and_only_for_cross_task_risk(self):
        self.assertIn("多个任务或跨服务契约", self.orchestration)
        self.assertIn("只审查跨任务风险", self.orchestration)
        self.assertIn("task-local", self.contract)
        self.assertIn('"axis": "integration"', self.skill)

    def test_quality_and_integration_preserve_independence_and_freshness(self):
        self.assertIn("quality 与 integration 初审必须使用 `blind`", self.contract)
        self.assertIn("`independent=true` 和全新上下文", self.contract)
        self.assertIn("源码变化后旧结果立即 stale", self.contract)

    def test_legacy_intent_blind_and_closure_requests_remain_readable(self):
        self.assertIn("protocol_version=2", self.contract)
        self.assertIn("protocol_version=1", self.contract)
        self.assertIn("intent", self.contract)
        self.assertIn("blind", self.contract)
        self.assertIn("closure", self.contract)
        self.assertIn("不得推断 axis", self.contract)


if __name__ == "__main__":
    unittest.main()
