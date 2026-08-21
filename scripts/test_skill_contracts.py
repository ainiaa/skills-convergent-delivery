import re
import subprocess
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
    def test_repository_does_not_track_generated_python_bytecode(self):
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "*.pyc"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual("", result.stdout.strip())
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", ignore)
        self.assertIn("*.py[cod]", ignore)

    def test_five_skills_have_distinct_names_and_triggers(self):
        paths = {
            "converge": ROOT / "SKILL.md",
            "converge-plan": ROOT / "skills/converge-plan/SKILL.md",
            "converge-review": ROOT / "skills/converge-review/SKILL.md",
            "converge-batch": ROOT / "skills/converge-batch/SKILL.md",
            "converge-eval": ROOT / "skills/converge-eval/SKILL.md",
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
        self.assertIn("evaluate", descriptions["converge-eval"].lower())

    def test_release_registers_eval_for_install_checks_and_both_runtimes(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        checks = (ROOT / "scripts/check.sh").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertEqual("0.17.0", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertIn(
            "SKILL_NAMES=(converge converge-plan converge-review converge-batch converge-eval)",
            installer,
        )
        for path in (
            "skills/converge-eval/SKILL.md",
            "skills/converge-eval/references/evaluation-contract.json",
            "skills/converge-eval/scripts/test_eval_contract.py",
            "references/evaluation-catalog.json",
            "references/review-orchestration.md",
        ):
            self.assertIn(path, installer)
        self.assertIn("converge-eval", checks)
        self.assertIn("skills/converge-eval/scripts/test_eval_contract.py", checks)
        self.assertIn(
            "skills/converge-review/scripts/test_review_axes_contract.py", checks
        )
        for runtime in ("Codex", "Claude Code"):
            self.assertIn(runtime, readme)
        self.assertIn("五个 Skill", readme)

    def test_plan_v5_and_checkpoint_commit_semantics_are_integrated(self):
        root_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        batch_skill = (ROOT / "skills/converge-batch/SKILL.md").read_text(encoding="utf-8")
        batch_contract = (ROOT / "skills/converge-batch/references/batch-contract.md").read_text(
            encoding="utf-8"
        )
        combined = root_skill + readme + batch_skill + batch_contract

        self.assertIn("Plan Contract v5", combined)
        self.assertIn("checkpoint=same_session", combined)
        self.assertIn("同会话顺序执行", combined)
        self.assertIn("不要求 commit", combined)
        self.assertIn("checkpoint=cross_session", combined)
        self.assertIn("跨会话", combined)
        self.assertIn("本地 commit 授权", combined)

    def test_planned_capsule_guard_precedes_task_profile_routing(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(text.index("planned_task=true"), text.index("task_profile.py"))

    def test_bounded_loops_have_distinct_termination_conditions(self):
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        for loop in ("实现循环", "风险复核循环", "全局集成审查循环"):
            self.assertIn(loop, control)
        for stop in (
            "红灯转绿",
            "最多一次修复和一次定向复核",
            "重复 finding",
            "执行一次 integration 审查",
            "本轮 active worker 数为 0",
        ):
            self.assertIn(stop, control)

    def test_final_reporting_separates_coverage_classes_without_blanket_claims(self):
        root_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        scenarios = (ROOT / "references/evaluation-scenarios.md").read_text(encoding="utf-8")
        combined = root_skill + readme + scenarios

        for result_class in ("known_acceptance", "history", "exploration", "uncovered"):
            self.assertIn(result_class, combined)
        self.assertIn("不得写“未发现任何问题”", combined)
        self.assertIn("工作区累计", combined)
        self.assertIn("Codex 单步角标", combined)

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
            "Provider Binding",
            "多个边界独立",
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

    def test_root_skill_plans_bounded_provider_runs_without_splitting_pdlc_internals(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("converge-plan", text)
        self.assertIn("planned_task=true", text)
        self.assertIn("独立可验收的业务切片", text)
        self.assertIn("PDLC task 内部仍整体委托", text)
        self.assertIn("execution-control.md", text)

    def test_provider_and_progress_contracts_remain_controller_owned(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        state = (ROOT / "references/state-schema.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        for marker in ("Converge 始终是 controller", "Provider Schema v2", "不能成为第二真相"):
            self.assertIn(marker, skill)
        for marker in ("Progress Receipt v1", "objective_revision", "不编造百分比或 ETA"):
            self.assertIn(marker, state + control)

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
        self.assertIn("commit_authorized", contract)

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
            "task_id",
            "owner_run_id",
            "may_dispatch=false",
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
