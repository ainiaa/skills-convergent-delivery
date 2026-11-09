# 已知审查问题修复与机制取舍

作者：Jeff.Liu

范围：2026-09-05 审查报告中的五个缺陷、native 依赖声明和旧 Review 协议说明。基线 `10ca06744e86a2308542c35d5d6eb2d4666fd477`。只修改本地 Suite，不启用自治、多模型或发布。

## 行为验收

| 控制链 | 修复与边界 | 可执行回归 |
|---|---|---|
| closure 初审 → 修复 → 最终复核 | 首次全量 closure 不扣复核额度；最终扣一次，不能重置耗尽预算。最后仍有 finding 可保存 blocked，不放行 complete | `test_delivery_state.py` 的 `test_full_closure_initial_preserves_budget_for_one_final_review`、`test_final_closure_findings_can_be_saved_as_blocked` |
| Eval 输入 → 工件 → 结论 | 当前没有 evaluator bridge，公共 API/CLI 在读工件前返回 uncovered；旧 fixture 只测试私有统计函数，明确 diagnostic | `test_eval_kernel.py` 的 `EvalAvailabilityTest` 与原有差分统计/防篡改回归 |
| capsule 启动 → stdin → thread id → 恢复 | 复用现有 prompt writer；stdin 未完成或失败不能凭 thread id 确认；期限内不能确认则 indeterminate，重复请求不再创建进程 | `test_capsule_dispatch.py` 的 `test_codex_large_capsule_timeout_includes_stdin_delivery`、`test_codex_checks_write_error_after_observing_writer_completion` 与已有派发失败回归 |
| Maven argv → 红绿回执 → Trace | runner-aware selector 同时用于参数存在性和语法校验；支持 mvn/mvnw 内嵌 selector，拒绝其他测试名 | `test_tdd_impact_guard.py` 的 `test_maven_embedded_selector_passes_the_full_trace_and_rejects_mismatch` |
| 验证开始 → 源码变化 → 回执 | 公共入口比较前后源码，漂移不签发回执；未改变源码的正常/失败/超时证据仍保留 | `test_evidence_contract.py` 的源码漂移、CLI、正常、失败、超时测试 |
| native 前置条件 → 实现 | 写入前检查 CLI、已有索引和 coverage 配置；不安装、不建索引、不修改阈值；最终仍需 rerun | `test_tdd_impact_guard.py` 的两个 `test_preflight_*` |

全量校验继续使用 `bash scripts/check.sh --full`。验收事实来自测试实际输出，不来自本表；本表不建立运行状态或第二套进度台账。

## 第三方机制复核

本轮先通过 Skills.sh 发现，再核对以下上游原始 Skill；只采用能对应已复现问题的机制。

| 来源 | 采用 / 不采用 | 原因及对应行为测试 |
|---|---|---|
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) 及其 `scripts/run_eval.py` | 采用旧版/新版同输入对照与耗时、token 分开记录；不增加新的评估平台 | 正式 Eval 能力缺失不能被统计测试掩盖；`EvalAvailabilityTest` 验证入口的明确未覆盖结果 |
| [Superpowers writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/testing-skills-with-subagents.md) | 采用先观察失败再修改规则；不复制完整编排 | 大 stdin、不完整投递、缺失前置能力分别有先失败的回归 |
| [Trail of Bits property-based-testing](https://github.com/trailofbits/skills/blob/master/plugins/property-based-testing/skills/property-based-testing/SKILL.md) | 采用状态不变量和反例；暂不新增 PBT 依赖 | 有限 closure 链验证预算消耗、终态与额外复核拒绝；现有 unittest 足够表达已知反例 |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 采用组件可运行与组合链验证；不增加 CI loop、记忆文件或更多角色 | full Trace 的 Maven 测试覆盖独立 selector 单测漏掉的组合缺陷；Eval 不再冒充已连通 |
| [Harness engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/harness-engineering/SKILL.md) | 保留旧判定快照；采用同质量优先简化；不增加注册表、签名服务 | 复用现有 writer 和 coverage resolver；不为了 Eval 增加无法验证的新 lifecycle |
| [planning-with-files](https://github.com/othmanadi/planning-with-files/blob/master/skills/planning-with-files/SKILL.md) | 采用恢复前核对现有持久记录；不复制三份可写进度文件 | capsule 重放测试核对同一 receipt，不重派；继续以原状态为真源 |

## 当前未覆盖

- 正式 locked differential、真实宿主 evaluator lifecycle：当前无 bridge，保持 uncovered；本轮修改后的判定器不能给自身放行。
- 简单任务真实成本：本轮未启动真实模型基准，不声称节省 token 或提高完成率。后续沿用既有 runner receipt，对相同的局部修复、Maven 修复、带一次 closure 修复任务作有/无 Skill 或旧/新版对照；报告完成率、人工介入次数、耗时和 token，缺失值保留 unknown。
- 前置检查只确认 CLI、索引目录与 coverage 配置可发现，不证明索引新鲜、测试插件可执行或覆盖率达标；最终命令和回执仍决定通过与否。

简单路径不因本轮新增 state、worker、后台进程或新的编排层；保持现有验证强度，待真实对照证据出现后再决定是否删减环节。

## 后续整体验证审查修复（基线 4ea7489）

- native 完成入口和 rerun 复用同一 coverage policy 校验。真实 `python -c pass` 回执在完成 CLI 被拒绝，正确策略通过，PDLC 可保留自身策略。
- 解析 coverage 的实际启动位置，拒绝 `echo pytest --cov-fail-under=85`、关闭采集与跳过检查的反例。保留 Python module、Vitest、.NET 与 JaCoCo 正常配置回归。
- 复用现有 runner 的进程组终止函数；在隔离 Git 目录复现并验证超时子进程不能延迟写入。清理边界仍为本次进程组，不新增宿主生命周期声明。
- pytest 普通文件 selector 接受，错误文件拒绝。

对应测试位于 `test_native_tdd_policy.py`、`test_evidence_contract.py`、`test_tdd_impact_guard.py` 和 `test_delivery_next.py`。旧状态单测原本未声明项目 coverage 配置；现在配置与被测状态共同放入临时 Git 项目，不放松生产校验，也不把 fixture 称为实际 coverage 测量。

参考取舍：采用 [LangChain eval-engineering](https://github.com/langchain-ai/langchain-skills/blob/main/config/skills/eval-engineering/SKILL.md) 的环境与判定器分离，落实为临时真实进程/CLI 的反例测试；不引入 Harbor 或新评测服务。沿用 HumanLayer 的组合链验证与 Trail of Bits 的不变量方法，分别对应完成入口/重跑一致性和超时后无延迟写入。已有测试能表达这四个反例，因此不增加 PBT 依赖。正式 Eval、真实成本对照的未覆盖结论仍有效。

## 2026-09-06 八项修复（基线 7e1f94b）

| 已知问题 | 验收与实现边界 | 行为回归 |
|---|---|---|
| 非测试命令绑定 selector | actual runner + runner 专属选择语法，拒绝 echo/true/python -c/collect-only | `test_selector_requires_an_actual_test_runner` 与真实 unittest 红绿 fixture |
| 图搜索成功误作影响证明 | 当前索引、精确唯一符号、直接边；无法证明保留 uncovered | `test_successful_unresolved_graph_output_is_not_impact_evidence`、`test_graph_requires_fresh_unique_symbols_and_real_edges` |
| 旧 coverage 数据被复用 | 只接受本次采集检查；拒绝 report-only/append | `test_report_only_commands_cannot_claim_fresh_coverage` |
| tag 后 latest 失败 | 获取 main 并在检查后切换，保留快进约束 | `test_real_tag_upgrade_preserves_previous_install_until_candidate_is_valid` |
| 普通/自治重复 writer | common-dir 身份、workspace 共享锁；旧租约原位兼容 | `test_workspace_writer_cannot_be_split_across_repo_identities` 与 Hook managed-state 生命周期 |
| 安装失败破坏旧版 | 校验完整候选在切换之前，拒绝本地改动 | 同一真实本地 Git tag/latest/坏候选生命周期测试 |
| Claude 重复 Stop | 复用续跑回执；源码/阶段/动作不变就 blocked 并清场 | `test_claude_repeated_stop_terminalizes_and_releases_the_writer`、`test_continuation_uses_source_and_action_progress_not_report_revisions` |
| blocked 报告无法保存 | 允许既有 report-only transition，不重新打开执行 | `test_blocked_report_history_can_advance_without_reopening_execution` |

复用上一轮已核对的参考：采用 [LangChain verifier-design](https://github.com/langchain-ai/langchain-skills/blob/main/config/skills/eval-engineering/references/verifier-design.md) 的实际效果与缺证据反例，落实为前三项门禁测试；采用 [Trail of Bits variant-analysis](https://github.com/trailofbits/skills/blob/master/plugins/variant-analysis/skills/variant-analysis/SKILL.md) 的同根因入口复核，覆盖普通/自治/迁移、Codex/Claude 与终态报告。采用 HumanLayer 的可运行组件链，使用真实临时 Git 仓验证安装生命周期。未引入新的评估平台、PBT 依赖、后台 loop、代理、可写状态或报告文件；现有 unittest 和回执足够表达本轮失败。

正式 evaluator bridge 仍缺失。本轮本地回归与锁定旧 controller 快照仅用于修复诊断，不构成真实宿主差分验收，不据此修改总分或宣称成本下降。


## 2026-09-06 结果分类与索引内容修复（基线 d9a9847）

验收冻结为两个已确认缺陷：目标失败不能作为 GREEN；状态正常但内容过期的索引不能作为 TDD/Plan/closure 图证据。沿用现有 helper、SQLite stdlib 和 unittest，不增加代理、可写状态、依赖或发布动作。

| 采用的机制 | 不采用及原因 | 对应行为验证 |
|---|---|---|
| [LangChain calibration](https://github.com/langchain-ai/langchain-skills/blob/main/config/skills/eval-engineering/references/calibration.md)：已知正确路径与误放行路径成对验证，区分环境故障和判定错误 | 不添加固定多模型采样；当前缺少 evaluator lifecycle bridge，不能产生正式差分证据 | `test_outcome_counts_preserve_normal_and_failure_results`、`test_success_exit_cannot_hide_failed_runner_outcomes` |
| [Trail of Bits fp-check](https://github.com/trailofbits/skills/blob/main/plugins/fp-check/skills/fp-check/SKILL.md)：核实具体触发条件和完整公共调用路径 | 不复制安全审计专用的代理编排；本次共享 seam 的确定性反例足够 | 真实 unittest 的 `test_real_expected_failure_is_not_green`；同一 SQLite 反例分别执行 impact 和 closure 查询 |
| [Trail of Bits code-maturity-assessor](https://github.com/trailofbits/skills/blob/main/plugins/building-secure-contracts/skills/code-maturity-assessor/SKILL.md)：固定评级依据并绑定证据 | 不套用智能合约九维度，也不因新增单测数量调整效果分；评分属于审查产物，不增加运行时打分器 | 既有五维评分口径保持不变；本轮不生成新的主观分数，正式 Eval 预检仍返回 uncovered |

测试结果保留 passed/failed/errors/skipped/xfailed/xpassed，GREEN 在共享入口验证，旧 executed-only 结果不能重新封装放行。Maven/Gradle/JS 分支使用本次真实子进程输出的协议夹具；不声称执行了实际 JVM/JS 测试。真实 unittest 证明 expectedFailure 的退出码 0 确实不能再通过 GREEN。

图适配复用本机 CodeGraph 1.0.1 的 files.content_hash（SHA-256）与 extraction-v24 后缀清单；只读 SQLite，不重建本仓索引。`test_clean_status_cannot_hide_stale_index_contents` 覆盖正常索引、保留尺寸/mtime 的内容变化、已提交新增 caller、删除、缺数据库与损坏数据库，并同时验证 impact 和 closure。查询期间的数据库变化也必须被拒绝。旧图状态无法证明当前源码时是环境 uncovered，不能以此撤销代码修复或伪造图回执。

仍未覆盖的能力：本仓没有 coverage 命令；正式 evaluator bridge 不可用；Maven/PIT 以外的 mutation 结果未适配；Gradle 无可识别汇总时保持 uncovered。它们不是这两个缺陷的替代修复，未通过放宽门槛、安装工具或调用真实模型来消除。后续适配必须用对应真实运行器的已知正确/错误场景验证，不预先生成空适配器。旧 controller 快照保存在仓库外，本轮新增 catalog 条目不能成为本轮候选自证通过的判定器。

## 后续评审机制与回归记录

2026-11-06 已知问题修复沿用既有状态与评测结果，不增加运行角色、可写台账或重试预算：

同日二次复核复用已有 `_run_command`，让交互判定器与候选测试共享进程组清场；依据 [Python subprocess 文档](https://docs.python.org/3/library/subprocess.html#subprocess.Popen) 的独立 session 机制，不再另造执行器。正常结束和超时均验证候选子进程已停止，保留共享剩余预算及相对工作区兼容。Python 工具缺模块/无法导入名称且没有已执行测试失败时复用 `tooling_failure=unavailable`，保留真实退出码 1；不以退出码或普通异常关键词推断其他运行时故障，不添加第二套状态。回归为 `test_judge_cleans_up_candidate_children_on_success_and_timeout`、`test_malformed_host_command_fields_are_uncovered_without_repair`、`test_local_test_exit_code_collision_does_not_claim_tool_unavailability`、`test_python_import_startup_failure_is_tooling_but_test_errors_are_business_failures`、`test_auditor_import_failure_does_not_authorize_a_business_repair`。

| 参考 | 采用 | 不采用及原因 | 行为测试 |
|---|---|---|---|
| [LangGraph interruption tests](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/tests/test_interruption.py) | 在持久化边界注入中断；修复预算、阶段与动作提交在同一次写入中生效 | 不引入 LangGraph 或额外日志，现有 action attempt 足以恢复下一动作 | `test_repair_commit_survives_a_crash_after_persistence_without_replaying` |
| [Anthropic grader](https://github.com/anthropics/skills/blob/main/skills/skill-creator/agents/grader.md) | 用空回复、漏问、依赖问题、空测试、错序与无效测试作反例；讨论回执核对事项和推荐，局部 TDD 同时核对宿主事件与候选测试正反执行 | 不用问号数量、模型自述或额外 LLM grader 放行。约束 JSON 只验该合成讨论；TDD 观测仅支持直接 unittest 与 apply_patch，其他执行形态不冒充通过 | `test_discussion_rejects_empty_missing_extra_and_unrecommended_decisions`、`test_local_tdd_rejects_reordered_missing_and_wrong_workspace_events`、`test_local_tdd_rejects_a_candidate_test_that_cannot_detect_the_original_bug` |
| [HumanLayer control loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 复用冻结画像，将接管范围内的已有 diff 作为路径风险下限 | 不建立第二风险登记表，不让范围外脏文件影响当前画像 | `test_existing_changes_add_only_owned_path_risks` |

真实 Codex smoke 发现旧快照遗漏 `references/inline-tdd.md`，局部任务因读取失败而额外加载完整 TDD 文档。Protocol 24 将已有引用加入核心资源清单，并在安装预检拒绝缺文件的源包；旧 Protocol 23 按既有历史快照验证路径保留，不修改旧内容或判定器。参考发现先核对 Skills.sh 的上下文类条目，再读 [filesystem-context](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/filesystem-context/SKILL.md)，采用按需读取相关文件，拒绝新增上下文台账或自动回填旧快照：本次缺陷是资源未打包，额外状态无法修复。回归：`test_inline_tdd_is_readable_from_core_and_host_eval_snapshots`、`test_inline_tdd_remains_frozen_when_the_live_reference_changes`、`test_missing_inline_tdd_blocks_snapshot_creation_before_writing`、`test_protocol_23_without_inline_tdd_remains_readable`、`test_install_rejects_a_suite_missing_inline_tdd`。

完整流程后续审查采用 [Superpowers systematic-debugging](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md) 对相似路径和依赖的核对，以及 [verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) 的证据边界；不引入新状态、额外代理或反复审查循环，避免让局部任务增负。`interaction_replay.py` 的 `full-flow-review` 用精简配置夹具重建扫描、试调用已修但其他入口仍绕过同一规则的失败：冻结判定覆盖手动配置、保存恢复、切换、启动，含空值、空白、非法类型、损坏存储与 I/O 错误；逐入口绕过验证都不能通过。`simple-local-fix` 保持单轮小夹具，并拒绝额外流程文件。对应回归在 `test_interaction_replay.py`；它们验证判定器能识别错误结果，不证明真实模型已经遵守指引，流程清单语义及未验证路径的报告仍须真实宿主另验。

本次先经 Skills.sh Agent workflows 分类发现，再核对 [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md)、本机 OpenAI skill-creator 和 [Context Engineering evaluation](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/evaluation/SKILL.md)：采用固定输入与可执行结果断言，并用局部任务负例检查影响边界；复用现有回放器，不增加运行时状态或代理。未采用 [advanced-evaluation](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/advanced-evaluation/SKILL.md) 的 LLM 评分：这些边界已有客观结果，模型打分只会增加成本和自评偏差。未复制 skill-creator 的多轮并行优化流程，本次仅补验证缺口。行为映射为 `test_full_flow_review_rejects_a_scan_only_fix_despite_a_success_claim`、`test_full_flow_judge_catches_each_unchecked_sibling_and_switch_boundary`、`test_simple_local_fix_rejects_unrequested_flow_files`。

受管理的 schema 10 run 在最终验证前由 `delivery_next.next_runtime_action` 检查当前源码指纹与各轴最新审查。范围内已确认缺陷复用 `run_contract.followup_action` 和现有一次修复预算；旧 findings 被后续 pass 覆盖后不再修复。未分类问题或预算耗尽返回 block。schema 11 继续使用已有自治审计。普通桌面对话只有 Skill 引导，不能宣称拥有结束/提问拦截能力。

本轮采用 HumanLayer 控制循环的显式下一动作和有限退出，复用现有机器状态；不增加第二套授权账本或常驻监督代理。行为回归：`test_final_verification_routes_unresolved_findings_to_bounded_repair`、`test_followup_never_repairs_out_of_scope_or_unclassified_issues`。采用 SkillOpt 官方 EnvAdapter 的四个环境方法及继承反思接口；不在运行时自动训练或修改判定器。回归：`test_skillopt_adapter.py` 与 `test_interaction_replay.py`。

| 参考 | 采用 | 不采用及原因 | 对应行为测试 |
|---|---|---|---|
| [Anthropic evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)、[Skill Creator grader](https://github.com/anthropics/skills/blob/main/skills/skill-creator/agents/grader.md)、[OpenAI harness-aware evals](https://developers.openai.com/cookbook/examples/partners/harness_aware_plugin_evals/harness_aware_plugin_evals) | 用真实解释器的正反对照先核实判定器，再检查 Product 合成成品的必要追问、禁止推断与已决保持；受控续修复用 `followup_action`，记录实际动作和输入来源 | 不复制多轮优化器，不新增状态或代理；约束 JSON 摘要不能证明任意 PRD 正文语义，宿主故障注入也不证明模型原先生成错误。仅在受控路径且产物通过时证明无需追加用户消息，普通 Skill 指引仍无硬拦截 | `test_verifier_preflight_requires_both_positive_and_negative_controls`、`test_product_case_repairs_without_an_additional_user_message`、`test_product_case_checks_unasked_questions_and_unsupported_decisions_together`、`test_product_failed_experiment_stops_without_resetting_its_single_repair_budget` |
| 本机 `skill-creator`、[Superpowers writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) | 先让已知问题穿过完成门禁，再补失败回归和单轮交互场景 | 不增设另一套可写问题台账；现有 `handoff.open_issues` 已是待处理真源 | `test_complete_rejects_known_open_issues_even_when_acceptance_passes`、`authorized-delivery-closes-review-findings` |
| [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | 最终声明绑定当前源码的通过证据，且已记录问题不能被 `attention` 包装为完成 | 不承诺未知 Bug 为零；测试与审查只能证明其覆盖的范围 | `test_complete_with_known_open_issues_cannot_render_as_attention` |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md)、本机 PDLC `loop-next` | 复用现有状态、单步决定和 `blocked` 停止条件 | 不引入定时控制器、额外 Hook 状态或无限修复循环；普通开发是一次已授权任务，不是持续巡检 | `test_structured_open_issues_preserve_the_exact_item_count`、现有 review 预算回归 |
| PDLC v1.7.17 `batch-review`（来源提交 `ef05bf2`；机制引入于 `f8d1aa2`） | 采用阶段性问题必须在最终交付闭环的原则；复用 Review v3 finding_records、最新轴结论与完成门禁 | 不增加 batch-review Markdown 台账或固定每 2～3 项的额外评审：现有任务级与集成审查已覆盖分层，第二台账会增加同步、恢复和简单任务成本 | `test_integration_local_defect_routes_to_repair_even_when_the_axis_passes`、`test_integration_local_defect_cannot_complete_with_an_empty_handoff`、`test_current_integration_pass_does_not_reopen_historical_local_defects` |
| [Superpowers writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md)、[multi-agent-patterns](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/multi-agent-patterns/SKILL.md) | 按独立可验收结果划定任务，只有明确上下文隔离收益才委派；参考发现先核对 Skills.sh Agent workflows/榜单，再读原始机制 | 不照搬逐阶段 fresh agent 或新增批次角色；当前缺陷由共享 helper 漏读既有记录造成，增加代理不能修复；不把安装量作为行为证据 | `test_integration_local_suggestion_does_not_add_a_repair`、`test_inline_route_rejects_low_risk_reviewer_and_host_only_roles` |

Core 的本地只读 reviewer 例外同样适用于仅启用 autonomy 的 native run；该扩展不等于 multimodel。实际失败请求在 launch 之前被拒绝，修复后仍校验本地 runner、reviewer 角色、read workspace、shell=false 和完整 Review v3 绑定。变更不允许 fan-out，也不增加角色或模型权限。回归 `test_autonomy_preserves_only_the_core_local_read_only_reviewer` 保留可写/shell/远端/scout/无 dispatch 的拒绝反例。

实际只读 Codex 执行暴露全局 Stop Hook 继承会抢占父任务的问题。新 leaf launch 将 hooks_enabled=false 纳入冻结配置并仅以 `-c features.hooks=false` 约束该子进程，不修改用户配置；保留 read-only/agent 禁用及旧 launch 原语义。角色请求、源指纹和 CAS 仍是结果写入前提，旧失败状态和未知回执不补猜、不重派同一 launch。新配置产生不同 launch 指纹；对应回归 test_new_leaf_launches_freeze_child_hook_isolation_without_changing_user_config。此配置键已由本机 `codex features list` 与 `codex exec --help` 核实。

后续改为按会话归属控制 Converge Stop 的写权。采用 [Codex Hooks](https://learn.chatgpt.com/docs/hooks) 和 [Claude Code Hooks](https://code.claude.com/docs/en/hooks) 的 `session_id`，沿用 [HumanLayer 控制循环](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) 将写入判断放在执行边界的做法。复用现有 runtime 字段和 CAS，无需另建身份账本。子进程全面关闭 Hooks 会一并关闭其日志和命令检查，因此新 launch 沿用宿主配置，已冻结的旧命令仍按原契约执行。回归通过真实 runner 入口启动替身 reviewer，执行 Converge Stop 和同级 Hook，核对父状态与租约原始字节，并验证未绑定或外来事件在冻结控制器之前退出。测试方法沿用 [Superpowers 行为回归](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) 的先复现再修正。

并行复审复现了冻结 Hook 重新扫描工作区后写到后来 run 的竞态。复用既有快照校验、`run_hook` 和 CAS。将已核对的 run、revision 和快照交给隔离解释器，由解释器读取该快照中的指定源文件。另按宿主事件类型跳过 `SubagentStop`，因为它可能携带父会话 ID。回归覆盖任务交接后的延迟 Stop、相同父会话 ID 的子代理事件、工作区同名模块和损坏的快照描述符。[Codex SubagentStop 契约](https://learn.chatgpt.com/docs/hooks#subagentstop)

再次复审确认，快照自校验和 Stop 内部的状态写入还会继承 Python 搜索路径，清单外字节码也能覆盖依赖。复用快照文件清单和同一个隔离启动入口，使校验和执行使用已核验源码，并清除控制器子进程继承的 Python 搜索配置。只读旧快照诊断仍走既有读取契约。回归分别向 `PYTHONPATH`、快照模块目录和依赖字节码注入替身，并核对正常 Stop 的 intent 确实落盘。无需引入新的进程沙箱或状态格式。[Python 解释器隔离选项](https://docs.python.org/3/using/cmdline.html#cmdoption-I)

将 CPython 的 `-S` 用于校验、冻结 Stop、写状态及释放租约。`-I` 仍可执行所选 Python 环境的 `.pth`，单靠环境变量也无法代替 `-S`。通过冻结 Stop 已有的进程入口补齐旧快照两条已验证控制命令的启动参数，沿用原快照代码和 CAS。未采用修改旧快照或关闭宿主 Hooks 的方案。临时虚拟环境中用无害的 `.pth` 标记先证明默认启动会执行，再验证当前及旧命令在正常续跑、无进展终止和释放租约时都不执行该标记。[Python `-S` 选项](https://docs.python.org/3/using/cmdline.html#cmdoption-S)

同样的启动隔离适用于 Codex 注册的 Converge 入口和本机 Stop 适配器。复用安装器的所有权记录，只替换可识别的命令，保留索引、分组、超时和同组 Hooks。沿用宿主按哈希审核的边界，避免重建注册或写入信任配置。回归测试使用带 `.pth` 标记的解释器执行实际注册命令，验证原位迁移、重复安装、回滚和旧快照续跑。[Codex Hook 信任](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)

## 已审计的分组覆盖率启动器与 Trace 容量

对 `python3 scripts/native-coverage.py` 的适配限于已经审计并钉住完整 SHA-256 的 YAM 启动器版本（测试夹具 `scripts/fixtures/yam-native-coverage-v1.txt`）。它执行官方 show-env → 清理 → 插桩编译 → 完整清单/ignored 对账 → 非空测试组执行 → 85% report 流程，禁止只准备缓存或添加未知参数。入口或脚本改变必须重新审计；目标高于 85% 保持 uncovered，不降门槛。Evidence 仍当次真实执行完整命令、核对执行前后 Source Receipt，不能导入旧日志。

参考 cargo-llvm-cov 官方 external tests 流程，采用其分步插桩和汇总；不将任意 Python 包装当作原生 runner，也不另建配置/运行时。Skills.sh verification-before-completion 用于发现，最终执行语义以原生工具源码和当前脚本为依据。行为回归：GroupedCargoCoverageLauncherTest、YAM test_empty_or_all_ignored_inventories_never_report_coverage；未知脚本、漂移、额外参数和较高目标均为拒绝反例。

Trace v5 载荷与 native 状态入口的上限统一为 4 MiB。该容量覆盖 YAM 当前约 114 KiB Source Receipt 的多项 RED/GREEN/风险证据组合，不删减重复来源证明或放松任何校验；超过上限仍在解析/校验入口拒绝。回归同时核对合法大工作区证据、指纹篡改和超限输入。
