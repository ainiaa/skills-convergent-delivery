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
            self.assertIn("compatibility: Requires Git and Python 3.11+", header)
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

        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"\A\d+\.\d+\.\d+\Z")
        for document in (readme, usage):
            self.assertIn(f"v{version}/install.sh", document)
            self.assertIn(f"--release {version}", document)
        self.assertIn(
            "CORE_SKILL_NAMES=(converge converge-plan converge-review converge-batch converge-eval)",
            installer,
        )
        self.assertIn(
            "EXTENSION_SKILL_NAMES=(converge-autonomy converge-multimodel)", installer,
        )
        self.assertIn(
            'SKILL_NAMES=("${CORE_SKILL_NAMES[@]}" "${EXTENSION_SKILL_NAMES[@]}")', installer,
        )
        for path in (
            "skills/converge-eval/SKILL.md",
            "skills/converge-eval/references/evaluation-contract.json",
            "skills/converge-eval/scripts/test_eval_contract.py",
            "references/evaluation-catalog.json",
            "references/review-orchestration.md",
            "evals/evals.json",
            "scripts/runner_registry.py",
            "scripts/codex_exec_runner.py",
            "scripts/openai_compatible_runner.py",
            "scripts/multi_model.py",
            "scripts/multi_model_smoke.py",
            "scripts/multi_model_repo_eval.py",
            "references/multi-model-repository-evaluation.json",
            "references/worker-runners.md",
            "references/multi-model.md",
            "scripts/test_trigger_evals.py",
        ):
            self.assertIn(path, installer)
        self.assertIn("converge-eval", checks)
        self.assertIn("skills/converge-eval/scripts/test_eval_contract.py", checks)
        self.assertIn("scripts/test_trigger_evals.py", checks)
        self.assertIn("scripts/test_multi_model_repo_eval.py", checks)
        self.assertIn("CONVERGE_CHECK_SELF_TEST=1 python3 scripts/test_check.py", checks)
        self.assertNotIn("fast_path.py", installer)
        self.assertNotIn("test_fast_path.py", checks)
        self.assertIn("scripts/test_runner_registry.py", checks)
        for test in (
            "scripts/test_runner_contract.py",
            "scripts/test_role_result.py",
            "scripts/test_role_fanout.py",
        ):
            self.assertIn(test, checks)
        self.assertIn(
            "skills/converge-review/scripts/test_review_axes_contract.py", checks
        )
        for runtime in ("Codex", "Claude Code"):
            self.assertIn(runtime, readme)
        self.assertIn("五个核心 Skill", readme)
        for extension in ("converge-autonomy", "converge-multimodel"):
            self.assertIn(extension, readme)
        self.assertIn("七个入口", usage)
        self.assertIn("七个目标", usage)
        self.assertIn("五个核心 Skill", usage)
        self.assertIn("converge-eval", usage)

    def test_release_notes_template_is_user_focused_and_evidence_honest(self):
        template = (ROOT / "docs/templates/release-notes.md").read_text(encoding="utf-8")
        usage = (ROOT / "docs/usage-guide.md").read_text(encoding="utf-8")

        for marker in (
            "## 这一版解决了什么",
            "## 重点内容：你现在可以",
            "## 修复",
            "## 验证",
            "## 已知发布证据限制",
        ):
            self.assertIn(marker, template)
        self.assertIn("templates/release-notes.md", usage)
        self.assertIn("面向使用者", usage)

    def test_ci_checkout_includes_the_parent_required_by_eval_kernel(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("uses: actions/checkout@v4\n        with:\n          fetch-depth: 2", workflow)
        self.assertIn('python-version: ["3.11", "3.14"]', workflow)
        self.assertIn("python-version: ${{ matrix.python-version }}", workflow)

    def test_registered_extensions_require_explicit_invocation(self):
        for extension in ("converge-autonomy", "converge-multimodel"):
            policy = (ROOT / "extensions" / extension / "agents/openai.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("allow_implicit_invocation: false", policy)

    def test_plan_v5_and_checkpoint_commit_semantics_are_integrated(self):
        root_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        batch_skill = (ROOT / "skills/converge-batch/SKILL.md").read_text(encoding="utf-8")
        batch_contract = (ROOT / "skills/converge-batch/references/batch-contract.md").read_text(
            encoding="utf-8"
        )
        combined = root_skill + readme + batch_skill + batch_contract

        self.assertIn("Plan Contract v6", combined)
        self.assertIn("checkpoint=same_session", combined)
        self.assertIn("同会话顺序执行", combined)
        self.assertIn("不要求 commit", combined)
        self.assertIn("checkpoint=cross_session", combined)
        self.assertIn("跨会话", combined)
        self.assertIn("本地 commit 授权", combined)

    def test_native_subagent_requires_a_host_observed_bridge_and_keeps_external_runner_separate(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )
        dispatch = (ROOT / "scripts/role_dispatch.py").read_text(encoding="utf-8")
        combined = root + control + runtime

        for marker in (
            "spawn_agent",
            "精确 `worker_ref`",
            "external_runner",
            "手工 capsule",
            "wake-up signal",
            "host_observed",
            "frozen route 为 `delegated`",
            "unexpected_refs",
        ):
            self.assertIn(marker, combined)
        self.assertIn('"executor": "external_runner"', dispatch)
        self.assertNotIn("send_input(interrupt", runtime)
        self.assertNotIn("Native Handoff", combined)

    def test_codex_cli_successor_and_chatgpt_desktop_subagent_are_distinct_adapters(self):
        dispatch = (ROOT / "references/capsule-dispatch.md").read_text(encoding="utf-8")
        desktop = (ROOT / "references/chatgpt-desktop-subagent.md").read_text(encoding="utf-8")
        root_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        for marker in ("codex exec --json", "thread.started.thread_id", "claude --background"):
            self.assertIn(marker, dispatch)
        for marker in (
            "spawn_agent", "wait_agent", "interrupt_agent", "当前会话", "不得降级", "leaf",
        ):
            self.assertIn(marker, desktop)
        self.assertIn("当前 package 将原生 child 视为 `unavailable`", desktop)
        self.assertIn("不能强制 child 作为 leaf", desktop)
        self.assertNotIn("spawn_agent({", desktop)
        self.assertNotIn("codex exec", desktop)
        self.assertIn("真实宿主 bridge", root_skill)

    def test_planned_capsule_is_guarded_before_the_routing_helper_contract(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")
        self.assertIn("planned_task=true", text)
        self.assertIn("task_profile.py", routing)
        self.assertIn("禁止再次规划", (ROOT / "references/execution-control.md").read_text(encoding="utf-8"))

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
        self.assertIn("空 findings 且 next_action=verify", runners)
        extension = (ROOT / "extensions/converge-multimodel/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("findings or a next action other than `verify`", extension)
        self.assertIn("工具", model)

    def test_multi_model_contract_distinguishes_role_labels_from_model_bound_workers(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        model = (ROOT / "references/multi-model.md").read_text(encoding="utf-8")
        extension = (ROOT / "extensions/converge-multimodel/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Multi-model external runners require the explicit", root)
        self.assertIn("常规 `role_flow` 路径", model)
        self.assertIn("`desktop-task` 和 `audit --execute`", model)
        self.assertIn("只有 `agent` 模式", model)
        self.assertIn("不会按 profile 切换模型", model)
        self.assertIn("not a complete role-level model orchestration", extension)
        self.assertIn("non-multi-model Converge delivery", extension)
        self.assertIn("serial", extension)
        self.assertIn("MCP", extension)
        self.assertRegex(extension, r"does not provide\s+a no-MCP configuration")

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

    def test_plan_skill_keeps_inline_work_outside_its_executable_contract(self):
        skill = (ROOT / "skills/converge-plan/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("只产出可执行 Plan", skill)
        self.assertIn("简单同会话任务走根入口的 `inline` 路径，不调用本 Skill", skill)
        self.assertLess(skill.index("只产出可执行 Plan"), skill.index("形成 Plan Contract"))

    def test_root_skill_plans_bounded_provider_runs_without_splitting_pdlc_internals(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        tdd = (ROOT / "references/tdd-providers.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        self.assertIn("converge-plan", text)
        self.assertIn("planned_task=true", text)
        self.assertIn("独立可验收", control)
        self.assertIn("pdlc-v1", tdd)

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
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")

        self.assertIn("generic-tdd-v1` 仅允许显式选择", skill + tdd)
        self.assertIn("简单 `inline` 不创建宿主计划项", skill + control)
        self.assertNotIn("简单任务直接显示五阶段计划", skill + control)
        self.assertIn("简单 `inline` 只读路由、TDD 和报告", skill)
        self.assertIn("简单 `inline` 不运行 `delivery_engine.py select`", skill)
        self.assertIn("references/inline-tdd.md", skill)
        self.assertIn("references/execution-topology.md", skill)
        self.assertIn("临时 Desktop ID", (ROOT / "references/host-capabilities.md").read_text(encoding="utf-8"))
        self.assertIn("不读取 worker、恢复、自治、多模型或全量收口协议", routing)

    def test_fast_path_is_disabled_without_a_semantics_aware_formatter(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")

        for marker in ("fast path", "通用 fast path 已停用", "formatter"):
            self.assertIn(marker, routing)
        for reference in (
            "references/task-routing.md",
            "references/tdd-providers.md",
            "references/reporting.md",
        ):
            self.assertIn(reference, skill)

    def test_writer_lease_is_required_without_loading_a_cli_recipe_for_inline_work(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        self.assertIn("writer lease", skill)
        self.assertIn("release", control)
        self.assertNotIn("delivery_lease.py\" release", skill)

    def test_provider_and_progress_contracts_remain_controller_owned(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        state = (ROOT / "references/state-schema.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        self.assertIn("Converge 始终是 controller", skill)
        for marker in ("Progress Receipt v1", "objective_revision", "不编造百分比或 ETA"):
            self.assertIn(marker, state + control)
        for marker in ("runner_launches", "runner_results", "completed"):
            self.assertIn(marker, state)

    def test_stepwise_requests_require_separate_visible_progress_messages(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        for marker in (
            "独立的 commentary 消息",
            "不得与下一步的开始合并",
            "文字降级",
        ):
            self.assertIn(marker, skill + control)
        self.assertIn("完成消息发送后，必须先结束该 commentary", skill)
        self.assertIn("下一步的开始只能在随后新的 commentary 中发送", skill)
        self.assertIn("不得在完成消息中声明、计划或调用下一步的动作", skill)
        self.assertIn("每个步骤边界都必须调用一次原生计划工具", skill)
        self.assertIn("不得只在初始建表或最终收口时批量更新", skill)
        self.assertIn("下一步开始 commentary 之后立即调用", skill)
        self.assertIn("同一次原生调用不得同时覆盖前一步完成和下一步开始", skill)
        self.assertIn("每个开始和完成边界都必须有一次成功的原生计划调用", control)
        self.assertIn("同一 `receipt_ref` 不得覆盖两个步骤边界", control)
        self.assertNotIn("一次真实调用可同时满足前步完成和后步开始", control)

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

    def test_state_schema_requires_host_observed_runtime_completion_policy(self):
        state = (ROOT / "references/state-schema.md").read_text(encoding="utf-8")
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("同会话、含 `tree_query` 的 `host_observed`", state)
        self.assertIn("controller_attested", state)
        self.assertIn("不能自动派发或清场", runtime)
        self.assertIn("不能派发、登记或清场", state)

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
        self.assertIn("同一个有冻结 profile", orchestration)

    def test_model_self_report_cannot_replace_real_execution_evidence(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        self.assertIn("模型自述不放行", skill)
        self.assertIn("不能只凭模型自述", control)
        self.assertIn("不为恶意篡改", control)

    def test_root_skill_preserves_honest_check_and_p0_e2e_boundaries(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        tdd = (ROOT / "references/tdd-providers.md").read_text(encoding="utf-8")

        for marker in (
            "命令不可用、超时或权限不足为 `uncovered`",
            "不得放松检查取得通过",
            "TDD 追溯](references/tdd-providers.md#tddimpact-trace-v5)",
            "--timeout-seconds",
            "ledger.tdd_trace",
        ):
            self.assertIn(marker, skill + tdd)

        for marker in (
            "每个 `criterion` 至少一个测试",
            "`normal`、`boundary`、`error`",
            "权限/并发/幂等",
            "编译、环境、Mock 等失败类型一律拒绝",
            "tdd_impact_guard.py",
            "native_tdd_policy.py",
            "`impacts[]`",
            "`entrypoint|caller|shared-effect|external-contract`",
            "公共 seam",
            "一个可观察行为",
            "mock 仅用于外部系统边界",
            "默认 >=85%",
            "test-commands.yml",
            "quality-targets.yml",
            "coverage 命令返回为 argv 并优先执行",
            "observed receipt",
            "failure_class",
            "selector",
            "runner selector",
            "CodeGraph",
            "稳定性 rerun",
            "`property` 场景",
            "ledger.tdd_trace",
            ".NET 的 `/p:Threshold=<n>`",
            "mutation",
            "pytest",
        ):
            self.assertIn(marker, tdd)

        for marker in ("Converge Suite", "CHANGELOG.md", "目标项目", "changelog"):
            self.assertIn(marker, skill)

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

    def test_active_write_authorization_survives_an_in_scope_review_checkpoint(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        activation = (ROOT / "references/activation.md").read_text(encoding="utf-8")
        protocol = (ROOT / "references/execution-protocol.md").read_text(encoding="utf-8")

        for marker in (
            "同一会话的写入授权持续有效",
            "仅审查",
            "同范围 finding",
            "不重复询问",
            "本轮真实验证",
        ):
            self.assertIn(marker, skill)
        self.assertNotIn("历史写入授权不得延续", skill)
        self.assertIn("持续中的写入任务", activation)
        self.assertIn("明确“仅审查”", activation)
        self.assertIn("审查检查点", protocol)
        self.assertIn("in-scope finding", protocol)

    def test_required_implementation_references_are_read_before_the_first_write(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        protocol = (ROOT / "references/execution-protocol.md").read_text(encoding="utf-8")

        for marker in (
            "`codex://`",
            "明确指定为实现依据",
            "需求真源",
            "另一套行为替代",
            "首次业务写入前",
            "普通背景链接不构成门禁",
            "持久化任务",
        ):
            self.assertIn(marker, skill + protocol)

    def test_route_reference_and_business_mapping_are_frozen_before_a_write(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")
        protocol = (ROOT / "references/execution-protocol.md").read_text(encoding="utf-8")

        for marker in (
            "实际执行 `task_profile.py`",
            "画像矛盾",
            "行为矩阵",
            "状态映射、重试或错误语义",
            "不得根据相似实现猜测",
        ):
            self.assertIn(marker, skill + routing + protocol)

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
            ROOT / "skills/converge-batch/SKILL.md",
            ROOT / "skills/converge-batch/references/runtime-adapters.md",
        ):
            self.assertIn("execution-control.md", path.read_text(encoding="utf-8"))

    def test_universal_completion_claims_require_a_finite_closure_matrix(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")
        scenarios = (ROOT / "references/evaluation-scenarios.md").read_text(encoding="utf-8")

        self.assertIn("全量收口", root)
        for marker in ("输入", "冻结", "副作用", "回执", "恢复", "uncovered"):
            self.assertIn(marker, control)
        self.assertIn("全量收口请求", scenarios)
        self.assertIn("不得宣称全部完成", scenarios)

    def test_full_closure_claims_stay_explicit_in_the_routing_contract(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        routing = (ROOT / "references/task-routing.md").read_text(encoding="utf-8")

        self.assertIn("全量收口必须显式选择", root)
        self.assertIn("task_profile.py", routing)
        self.assertNotIn("--request-file <raw-request>", routing)
        self.assertIn("full_closure_required=<bool>", routing)

    def test_authorized_plan_can_continue_across_a_known_tooling_gap(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        plan = (ROOT / "skills/converge-plan/SKILL.md").read_text(encoding="utf-8")
        control = (ROOT / "references/execution-control.md").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "scripts/plan_execution.py").is_file())
        for marker in (
            "plan_execution.py",
            "implementation_authorized",
            "tooling",
            "uncovered",
            "不得将",
        ):
            self.assertIn(marker, root + plan + control)

    def test_nonterminal_work_items_are_feature_scoped_and_inline_stays_stateless(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        protocol = (ROOT / "references/execution-protocol.md").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "scripts/work_item.py").is_file())
        for marker in ("work_item.py", "active/blocked", "功能", "一次性", "不落盘"):
            self.assertIn(marker, root + protocol)
        for marker in ("workspace、baseline", "语义 contract", "target", "回执"):
            self.assertIn(marker, root + protocol)

    def test_nonterminal_verifier_retry_uses_controlled_observed_evidence(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        protocol = (ROOT / "references/execution-protocol.md").read_text(encoding="utf-8")

        for marker in ("work_item.py verify", "相同源码", "恢复回执", "--recovery-receipt", "不得重复", "Evidence Receipt"):
            self.assertIn(marker, root + protocol)

    def test_nonterminal_verification_uses_the_controlled_evidence_runner(self):
        root = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        protocol = (ROOT / "references/execution-protocol.md").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "scripts/work_item.py").is_file())
        for marker in ("work_item.py verify", "Evidence Receipt", "不得直接运行"):
            self.assertIn(marker, root + protocol)


if __name__ == "__main__":
    unittest.main()
