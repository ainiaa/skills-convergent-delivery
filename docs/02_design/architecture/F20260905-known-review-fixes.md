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
