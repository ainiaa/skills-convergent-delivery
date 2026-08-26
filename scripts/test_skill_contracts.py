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
            self.assertIn("compatibility: Requires Git and Python 3.9+", header)
            self.assertIn("complete Converge Suite", header)
            self.assertIn("Codex and Claude Code", header)

        self.assertIn("implement", descriptions["converge"].lower())
        self.assertIn("plan", descriptions["converge-plan"].lower())
        self.assertIn("read-only", descriptions["converge-review"].lower())
        self.assertIn("batch", descriptions["converge-batch"].lower())
        self.assertIn("evaluate", descriptions["converge-eval"].lower())

    def test_release_registers_eval_for_install_checks_and_both_runtimes(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        checks = (ROOT / "scripts/check.sh").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        usage = (ROOT / "docs/usage-guide.md").read_text(encoding="utf-8")

        self.assertEqual("0.0.21", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
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
            "evals/evals.json",
            "scripts/fast_path.py",
            "scripts/test_fast_path.py",
            "scripts/runner_registry.py",
            "scripts/codex_exec_runner.py",
            "scripts/openai_compatible_runner.py",
            "scripts/multi_model.py",
            "references/worker-runners.md",
            "references/multi-model.md",
            "scripts/test_trigger_evals.py",
        ):
            self.assertIn(path, installer)
        self.assertIn("converge-eval", checks)
        self.assertIn("skills/converge-eval/scripts/test_eval_contract.py", checks)
        self.assertIn("scripts/test_trigger_evals.py", checks)
        self.assertIn("scripts/test_fast_path.py", checks)
        self.assertIn("scripts/test_runner_registry.py", checks)
        self.assertIn(
            "skills/converge-review/scripts/test_review_axes_contract.py", checks
        )
        for runtime in ("Codex", "Claude Code"):
            self.assertIn(runtime, readme)
        self.assertIn("五个 Skill", readme)
        self.assertIn("五个入口", usage)
        self.assertIn("五个目标", usage)
        self.assertIn("五个 Skill", usage)
        self.assertIn("converge-eval", usage)

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

    def test_multi_model_contract_has_fixed_roles_and_dynamic_flow(self):
        model = (ROOT / "references/multi-model.md").read_text(encoding="utf-8")
        runners = (ROOT / "references/worker-runners.md").read_text(encoding="utf-8")
        for role in ("router", "scout", "specifier", "implementer", "verifier", "reviewer", "adjudicator"):
            self.assertIn(role, model)
        self.assertIn("每次只选择一个下一角色", model)
        self.assertIn("可选运行实例", model)
        self.assertIn("role_dispatch.py", model)
        self.assertIn("external_runner", model)
        self.assertIn("受限 CLI", model)
        self.assertIn("claude_exec_runner.py", model)
        self.assertIn("不把 `max_turns` 伪称为 Codex CLI", model)
        self.assertIn("只有 `implementer`", runners)
        self.assertIn("工具", model)

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
        tdd = (ROOT / "references/tdd-providers.md").read_text(encoding="utf-8")
        self.assertIn("converge-plan", text)
        self.assertIn("planned_task=true", text)
        self.assertIn("独立可验收的业务切片", text)
        self.assertIn("完整 PDLC v1", tdd)
        self.assertIn("execution-control.md", text)

    def test_pdlc_selection_requires_explicit_frozen_entrypoint_activation(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        batch = (ROOT / "skills/converge-batch/SKILL.md").read_text(encoding="utf-8")
        combined = root + control + batch

        for marker in (
            "冻结 entrypoint",
            "$pdlc-feature|fix|refactor",
            "`pdlc-run` 不算调用",
            "禁止 native 混入",
        ):
            self.assertIn(marker, combined)

    def test_plan_freezes_bindings_with_the_deterministic_engine_output(self):
        skill = (ROOT / "skills/converge-plan/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("delivery_engine.py\" freeze-binding", skill)
        self.assertIn("--kind <feature|fix|refactor>", skill)

    def test_simple_inline_path_skips_generic_discovery_and_host_plan_ui(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        tdd = (ROOT / "references/tdd-providers.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        self.assertIn("generic-tdd-v1` 仅允许显式选择", skill + tdd)
        self.assertIn("简单 `inline` 不创建宿主计划项", skill + control)
        self.assertNotIn("简单任务直接显示五阶段计划", skill + control)
        self.assertIn("仅当路由不是 `inline`", skill)
        self.assertNotIn("\n读取 [计划执行与无响应保护]", skill)

    def test_fast_path_is_disabled_without_a_semantics_aware_formatter(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")

        for marker in (
            "fast path",
            "通用 fast path 已停用",
            "formatter",
            "完整路径",
        ):
            self.assertIn(marker, skill + routing)
        for reference in (
            "references/task-routing.md",
            "references/execution-control.md",
            "references/state-schema.md",
            "references/tdd-providers.md",
            "references/reporting.md",
        ):
            self.assertIn(reference, skill)
        self.assertLess(len(skill.encode("utf-8")), 2700)

    def test_writer_lease_has_an_exact_terminal_release_recipe(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("delivery_lease.py\" release", skill)
        for argument in ("--root", "--repo", "--workspace", "--task-key", "--run-id", "--writer-id"):
            self.assertIn(argument, skill)
        self.assertIn('"status":"released"', skill)

    def test_provider_and_progress_contracts_remain_controller_owned(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        state = (ROOT / "references/state-schema.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        for marker in ("Converge 始终是 controller", "Provider Schema v2", "不能成为第二真相"):
            self.assertIn(marker, skill)
        for marker in ("Progress Receipt v1", "objective_revision", "不编造百分比或 ETA"):
            self.assertIn(marker, state + control)
        for marker in ("runner_launches", "runner_results", "completed"):
            self.assertIn(marker, state)

    def test_root_skill_no_longer_owns_plan_or_review_modes(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("使用 `plan`", text)
        self.assertNotIn("使用 `review`", text)
        self.assertIn("converge-review", text)
        self.assertIn("converge-batch", text)
        self.assertIn('"$CONVERGE_SKILL_DIR/scripts/delivery_engine.py"', text)

    def test_documented_helpers_resolve_from_the_selected_skill(self):
        root_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        eval_skill = (ROOT / "skills/converge-eval/SKILL.md").read_text(encoding="utf-8")
        review_skill = (ROOT / "skills/converge-review/SKILL.md").read_text(encoding="utf-8")
        review_contract = (ROOT / "skills/converge-review/references/review-contract.md").read_text(
            encoding="utf-8"
        )
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")
        reporting = (ROOT / "references/reporting.md").read_text(encoding="utf-8")
        scenarios = (ROOT / "references/evaluation-scenarios.md").read_text(encoding="utf-8")
        state = (ROOT / "references/state-schema.md").read_text(encoding="utf-8")
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("记为 `CONVERGE_SKILL_DIR`", root_skill)
        self.assertIn("记为 `CONVERGE_EVAL_SKILL_DIR`", eval_skill)
        self.assertIn("记为 `CONVERGE_REVIEW_SKILL_DIR`", review_skill)
        self.assertIn('"$CONVERGE_EVAL_SKILL_DIR/../../scripts/controller_snapshot.py"', eval_skill)
        self.assertIn('"$CONVERGE_REVIEW_SKILL_DIR/scripts/review_contract.py"', review_skill)
        self.assertIn('"$CONVERGE_REVIEW_SKILL_DIR/scripts/review_contract.py"', review_contract)
        self.assertIn('"$CONVERGE_SKILL_DIR/scripts/task_profile.py"', routing)
        self.assertIn('"$CONVERGE_SKILL_DIR/scripts/delivery_report.py"', reporting)
        self.assertIn('"$CONVERGE_SKILL_DIR/scripts/delivery_state.py"', state)
        self.assertIn('"$CONVERGE_BATCH_SKILL_DIR/../../scripts/runtime_adapter.py"', runtime)

    def test_state_schema_matches_trusted_local_runtime_completion_policy(self):
        state = (ROOT / "references/state-schema.md").read_text(encoding="utf-8")
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("当前会话的可信本地宿主", state)
        self.assertIn("controller_attested", state)
        self.assertIn("可自动派发和清场", runtime)
        self.assertNotIn("只能支撑 blocked 清场，不能支撑带 worker 的 complete", state)

    def test_risk_and_metric_references_keep_inference_and_observation_honest(self):
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")
        reporting = (ROOT / "references/reporting.md").read_text(encoding="utf-8")
        scenarios = (ROOT / "references/evaluation-scenarios.md").read_text(encoding="utf-8")
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("语义风险声明", routing)
        self.assertIn("路径标记只能作为风险下限", routing)
        self.assertIn("指纹校验的 runner 回执", reporting)
        self.assertIn("不可用", reporting)
        self.assertIn("语义风险未声明", scenarios)
        self.assertIn("指标缺失", scenarios)
        self.assertIn("不伪造", runtime)

    def test_current_review_findings_require_records_but_old_rounds_remain_readable(self):
        state = (ROOT / "references/state-schema.md").read_text(encoding="utf-8")

        self.assertIn("当前 round 的 finding", state)
        self.assertIn("历史 round 可只保留 fingerprint", state)

    def test_review_independence_means_a_fresh_context_from_the_implementer(self):
        protocol = (ROOT / "skills/converge-review/references/review-contract.md").read_text(
            encoding="utf-8"
        )
        orchestration = (ROOT / "references/review-orchestration.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("`independent=true` 和全新上下文", protocol)
        self.assertIn("而不是为 spec 与 quality 各派一个 reviewer", protocol)
        self.assertIn("同一个已登记", orchestration)

    def test_model_self_report_cannot_replace_real_execution_evidence(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        self.assertIn("模型自述不放行", skill)
        self.assertIn("不能只凭模型自述", control)
        self.assertIn("不为恶意篡改", control)

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
        for marker in ("shared", "blind", "finding", "closure"):
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

    def test_claude_automatic_mode_requires_observed_session_capabilities(self):
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )

        for marker in ("当前会话", "Agent", "task list", "query=false", "手工交接"):
            self.assertIn(marker, runtime)

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
