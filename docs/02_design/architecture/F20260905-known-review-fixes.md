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
