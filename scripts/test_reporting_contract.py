import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ReportingContractTest(unittest.TestCase):
    def test_skill_routes_final_reports_to_the_user_receipt_contract(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("[交付回执](references/reporting.md)", skill)
        self.assertIn("只报告当前证据能证明的范围", skill)
        self.assertIn("确定性回归、真实宿主 smoke 和模型成本分别说明", skill)

    def test_reporting_contract_protects_decisions_and_hides_internal_noise(self):
        report = (ROOT / "references/reporting.md").read_text(encoding="utf-8")

        self.assertIn("`decision` 优先于 `ready`", report)
        self.assertIn("只报告相对上一份回执的变化", report)
        self.assertIn("不得出现 `complete`", report)
        self.assertIn("不得重新跑检查来凑报告内容", report)
        self.assertIn("`decision` | 160–260 字", report)
        self.assertIn("当前实现能做什么", report)
        self.assertIn("未验证范围和实际影响", report)
        self.assertIn("过程：<交付轮数", report)

    def test_reporting_separates_deterministic_checks_from_host_behavior_and_cost(self):
        report = (ROOT / "references/reporting.md").read_text(encoding="utf-8")

        for marker in ("确定性回归", "真实宿主 smoke", "模型成本", "uncovered"):
            self.assertIn(marker, report)


if __name__ == "__main__":
    unittest.main()
