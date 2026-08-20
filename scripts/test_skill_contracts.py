import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError(f"missing frontmatter: {path}")
    return text, match.group(1)


class SkillContractTest(unittest.TestCase):
    def test_four_skills_have_distinct_names_and_triggers(self):
        paths = {
            "converge": ROOT / "SKILL.md",
            "converge-plan": ROOT / "skills/converge-plan/SKILL.md",
            "converge-review": ROOT / "skills/converge-review/SKILL.md",
            "converge-batch": ROOT / "skills/converge-batch/SKILL.md",
        }
        descriptions = {}
        for name, path in paths.items():
            text, header = frontmatter(path)
            self.assertIn(f"name: {name}", header)
            description = next(line for line in header.splitlines() if line.startswith("description:"))
            descriptions[name] = description
            self.assertGreater(len(text), len(header))

        self.assertIn("implement", descriptions["converge"].lower())
        self.assertIn("plan", descriptions["converge-plan"].lower())
        self.assertIn("read-only", descriptions["converge-review"].lower())
        self.assertIn("batch", descriptions["converge-batch"].lower())

    def test_plan_skill_is_planning_only_and_defines_bounded_execution(self):
        skill = (ROOT / "skills/converge-plan/SKILL.md").read_text(encoding="utf-8")
        contract = (ROOT / "skills/converge-plan/references/plan-contract.md").read_text(
            encoding="utf-8"
        )
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        for marker in ("不修改业务代码", "provider", "Plan Contract", "plan_check.py"):
            self.assertIn(marker, skill + contract)
        for marker in (
            "planned_task=true",
            "pdlc-run",
            "90",
            "180",
            "最多自动恢复一次",
            "同一 `worker_ref`",
        ):
            self.assertIn(marker, skill + contract + control)
        for marker in ("DONE", "PARTIAL", "NOT_DONE", "CHANGED", "scope_drift"):
            self.assertIn(marker, contract)
        for marker in ("--workspace", "commit_id", "tree_hash", "diff_fingerprint", "exit_code"):
            self.assertIn(marker, contract)

    def test_root_skill_plans_before_non_planned_execution_without_splitting_pdlc(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("converge-plan", text)
        self.assertIn("planned_task=true", text)
        self.assertIn("一个 `pdlc-run`", text)
        self.assertIn("完整 PDLC", text)
        self.assertIn("execution-control.md", text)

    def test_root_skill_no_longer_owns_plan_or_review_modes(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("使用 `plan`", text)
        self.assertNotIn("使用 `review`", text)
        self.assertIn("converge-review", text)
        self.assertIn("converge-batch", text)
        self.assertIn('"$CONVERGE_SKILL_DIR/scripts/delivery_engine.py"', text)

    def test_activation_is_discoverable_but_never_edits_user_configuration(self):
        skill, header = frontmatter(ROOT / "SKILL.md")
        activation = (ROOT / "references/activation.md").read_text(encoding="utf-8")
        metadata = (ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        for marker in ("实现", "修复", "重构", "按方案修改", "修复已知问题"):
            self.assertIn(marker, header)
        self.assertIn("references/activation.md", skill)
        self.assertIn("AGENTS.md", activation)
        self.assertIn("不自动修改", activation)
        self.assertIn("allow_implicit_invocation: true", metadata)

    def test_review_skill_is_read_only_and_freshness_bound(self):
        skill = (ROOT / "skills/converge-review/SKILL.md").read_text(encoding="utf-8")
        contract = (ROOT / "skills/converge-review/references/review-contract.md").read_text(
            encoding="utf-8"
        )
        for marker in ("只读", "不得修改", "source_fingerprint", "independent"):
            self.assertIn(marker, skill + contract)
        for marker in ("intent", "blind", "finding", "closure"):
            self.assertIn(marker, contract)

    def test_batch_skill_is_scheduler_only_and_has_full_contract(self):
        skill = (ROOT / "skills/converge-batch/SKILL.md").read_text(encoding="utf-8")
        contract = (ROOT / "skills/converge-batch/references/batch-contract.md").read_text(
            encoding="utf-8"
        )
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )
        for marker in ("不读取业务代码", "不做代码评审", "$converge", "预检"):
            self.assertIn(marker, skill)
        self.assertIn('"$CONVERGE_BATCH_SKILL_DIR/scripts/batch_state.py"', skill)
        self.assertIn("runtime-adapters.md", skill)
        for marker in (
            "dispatch_id",
            "context capsule",
            "receipt",
            "final_acceptance",
            "planned_task",
            "plan_id",
            "task_id",
            "scheduler lease",
            "recovery_count",
            "pause",
            "resume",
            "stop",
        ):
            self.assertIn(marker, contract)
        for marker in (
            "Codex",
            "Claude Code",
            "执行控制",
            "结构化 receipt",
            "手工交接",
        ):
            self.assertIn(marker, runtime)
        self.assertIn("Batch Protocol v1 默认顺序", skill)

    def test_watchdog_rules_do_not_claim_missing_host_capabilities(self):
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )
        for marker in ("不是 `SKILL.md` 自带", "宿主", "不能声称", "手工恢复"):
            self.assertIn(marker, control)
        self.assertIn("execution-control.md", runtime)

    def test_worker_lifecycle_is_registered_owned_and_cleaned_before_exit(self):
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        for marker in (
            "run-scoped worker registry",
            "worker_role",
            "owner_run_id",
            "worker_status",
            "completed|interrupted|blocked",
            "等价 `finally`",
            "自然语言回执",
            "本轮存在 active worker",
            "历史孤儿",
        ):
            self.assertIn(marker, control)
        for path in (
            ROOT / "SKILL.md",
            ROOT / "skills/converge-batch/SKILL.md",
            ROOT / "skills/converge-batch/references/runtime-adapters.md",
        ):
            self.assertIn("execution-control.md", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
