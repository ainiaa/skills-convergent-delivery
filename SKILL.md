---
name: converge
description: "Use when implementing, fixing, or refactoring authorized software work (实现/修复/重构/按方案修改/修复已知问题), including same-session in-scope review findings. Multi-model external runners require the explicit converge-multimodel extension; not for standalone read-only review or multi-Batch."
metadata:
  compatibility: Requires Git and Python 3.11+; native runtime tasks require an indexed CodeGraph CLI and configured coverage; full-closure audits also require CodeGraph. Install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge：单任务闭环执行

Converge 始终是 controller，负责同一会话内已授权的软件交付；规划用 `converge-plan`，独立只读审查用 `converge-review`。触发见 [激活](references/activation.md)。

## 单任务交付契约

用户的目标是：**新需求或 Bug 修复 → 确定范围与验收 → 确定实现逻辑和回归风险 → 实现、复核并结束**。在同一个已授权 task 中，先冻结要改变和要保持的行为，再按 TDD 实现；对本次范围及受影响调用面做最终复核。发现可复现的同范围缺陷时，直接补回归测试、修根因、重新验证并复核，不把“已完成，另有 Bug 待修”交给用户，也不等待“继续修复”。

`complete` 只表示当前源码满足冻结验收、有新鲜验证证据、所需复核通过，且**没有已知未解决的同范围缺陷**；不得承诺未知 Bug 为零。检查不可运行、需要业务/权限/范围外决定，或同一根因无进展、有限预算耗尽时，保留问题与证据，明确 `blocked/uncovered`，不能改写成完成。只读审查、新会话和用户停止的授权边界仍按下文执行。

## 每轮约束

- 同一会话的写入授权持续有效，但仅限同一已冻结事项；交付报告不撤销授权，用户明确“仅审查/不要修改”、停止、取消，或转向范围外的新目标则撤销或结束该授权。`complete` 是上轮证据的终态，不是授权撤销。不得仅凭相同 workspace 或 Hook `session_id` 推定当前话题仍是该事项。
- 已授权事项中的审查是只读检查点：先确认 finding，再对同范围 finding 直接补红灯、修复、验证和复核，不要求用户再说“继续修复”。交付后或当前复核额度耗尽后发现可复现的不同同范围 Bug，保留旧回执，按 [审查编排](references/review-orchestration.md) 在同一会话开启新的有限修复轮次；同一 finding 无源码或证据进展时阻塞，不能通过重开轮次清零预算。范围外 finding 只记录影响并一次提出所需决定。
- 新会话的“还有问题吗”只授权检查与报告，发现问题后询问是否修复；新会话若已明确要求修复，则直接按新授权执行，不二次确认。身份、事项或范围无法核实时不借用旧授权；Hook 缺失或未信任也不得声称自动续修已生效。
- 先从当前任务、代码、测试和已决事项取得答案；不重复询问。只在业务规则、公共兼容、权限、发布或不可逆操作需要决定时提问，并给出一个推荐。
- 每个 finding 必须是修复、阻塞决策或范围外记录之一；不以建议替代同范围闭环。
- 模型自述不放行。没有本轮真实验证的验收不得称完成；命令不可用、超时或权限不足为 `uncovered`，不得放松检查取得通过。
- 用户明确指定为实现依据的引用（包括 `codex://`）是需求真源，不是背景提示。首次业务写入前必须通过当前宿主实际读取，并据此冻结范围与验收；不得未读参考就猜测实现，或用另一套行为替代。若引用未规定内部细节，沿用项目既有模式作最小选择；若其对完成需求必需但不可访问则阻塞。普通背景链接不构成门禁；持久化任务记录精确 reference 与读取结果，`inline` 任务在交付中说明已读取。
- 用户将具体项目、目录、分支或实现明确指定为唯一基准，并要求“对齐、保持一致、迁移”或“按其修改”时，按 [参考基准对齐](references/reference-alignment.md) 执行。它不是普通参考：首次业务写入前必须冻结相关文件的差异清单；参考基准变更即使仍在同一项目，也必须作废旧清单并重新比较。
- 首次终态回复前，一个用户任务必须在当前 task 内完成有限的构建、全范围复审、修复批和最终复核；若合法的同范围修复仍能继续，不得提前给出最终回执。安装 autonomy 后，Codex 的明确快捷指令“继续修复”/“继续修复已知问题”/`continue repair` 会在 `UserPromptSubmit` 受限地 arm 当前 workspace 的 repair gate，随后 Stop Hook 以原生 `decision:block` 在同一 task 交付一次冻结动作，绝不创建 successor task。该快捷门禁只是执行辅助；普通 task 不依赖它来完成首次闭环，也不以无用户消息重新开启已完成事项。
- 按需读取 reference：简单 `inline` 只读路由、TDD 和报告，其中 TDD 先读 [Inline TDD](references/inline-tdd.md)；计划、跨会话、自治、多模型或全量收口才读对应 contract。

用户要求“逐步修复 / 分步执行 / 按计划一步步做”时，按需读取并执行 [分步可见交付](references/execution-control.md#分步可见交付)。

## 开始与验证

将本目录记为 `CONVERGE_SKILL_DIR`。任何写入任务先按 [任务路由](references/task-routing.md) 逐字段填写画像并实际执行 `task_profile.py`，再冻结验收、范围和基线；画像矛盾、未读指定参考或未决业务映射均不得首次业务写入。只改任务 diff；外发和不可逆操作单独询问。简单 `inline` 不运行 `delivery_engine.py select`，直接按 [Inline TDD](references/inline-tdd.md) 完成局部红绿和报告。运行时功能、修复和重构先写可执行测试，再改生产代码；完整 red/green、影响、覆盖率和 Provider 规则见 [TDD 追溯](references/tdd-providers.md#tddimpact-trace-v5)。

仅 `planned`、`delegated`、`batch` 路由或用户明确要求 Provider binding 时选择并冻结 Provider：
```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_engine.py" select --mode <auto|pdlc|native> --kind <feature|fix|refactor>
```

Provider 选择冻结为 `native-v1` 或 `pdlc-v1`；native-v1 在首次业务写入前执行 `tdd_impact_guard.py preflight`，最终使用其 `rerun` 绑定当前源码。没有 CodeGraph、coverage 或可执行检查时保持 `uncovered`，不安装、不建索引、不降门槛。修改 Converge Suite 时更新本仓 `CHANGELOG.md` 的 `Unreleased`；目标项目的写入任务按其约定更新 changelog。

## 路由与终态

`planned_task=true` 只执行冻结 capsule。复杂、未知或长任务先用 `converge-plan`；同仓库并发写入先通过 [执行拓扑](references/execution-topology.md)，否则顺序执行；只有明确跨会话 checkpoint 才用 `converge-batch`。全量收口必须显式选择并使用 Plan matrix，不能由关键词推断。

用户已同时授权计划和实现时，Plan 校验的已知 `tooling` 未覆盖不得撤销 `implementation_authorized`。控制器必须运行 `python3 scripts/plan_execution.py --task-id <冻结首任务> --implementation-authorized --validation-error <原始错误>`；只有其 `execute` 输出才进入首个冻结实现步骤，并将错误如实记录为 `uncovered`。不得将 CodeGraph/回执能力缺口当作业务、权限或计划契约阻塞；其他错误仍由 helper 返回 `blocked`，不得自行降级。

一次性 `inline` 任务不落盘。只有需要跨轮修复或已进入 `active/blocked` 的功能事项才运行 `python3 scripts/work_item.py resume ...`：它以 workspace、baseline、功能 target、需求、验收、已决 decision 与 reference receipt 冻结唯一 work item，并只恢复全量相同的唯一事项；任何基线或语义 contract 漂移都阻塞，不能按项目名或相似引用猜测续接。功能级引用必须在回执中绑定该 target、关系和行为矩阵，不能把同项目其他功能当作语义副本。

对已落盘事项，验证必须通过 `work_item.py verify` 执行；它只接受事项冻结的 workspace/baseline，并在同一事项锁内完成 gate、Evidence Receipt 命令和失败落盘。不得直接运行冻结 verifier argv。相同源码与 argv 的失败返回 `blocked`，不得重复执行；只有源码、argv 或通过 `--recovery-receipt` 提供的新的同一源码 observed pass 回执才可重试。同一恢复回执只能释放一次重试。所有最终验收完成后，控制器只能将该事项 `verify` 已记录的当前源码 passing receipt 交给 `work_item.py complete` 清除非终态事项；任意无关命令、恢复回执或模型自述都不能完成或清场。

持久状态使用既有 writer lease，并按 [执行协议](references/execution-protocol.md) 和 [状态](references/state-schema.md) 清场。风险等级对应的复核边界见 [审查编排](references/review-orchestration.md)；Desktop、CLI 与 subagent 的可证明边界见 [宿主能力](references/host-capabilities.md)。没有真实宿主 bridge 时，不把本地 state、capsule、子任务或模型自述称为自动续跑、完成或清场证据。

最终按 [交付回执](references/reporting.md) 只报告当前证据能证明的范围；确定性回归、真实宿主 smoke 和模型成本分别说明。外发另行授权；Suite 行为改动先运行 `converge-eval` 的 deterministic preflight，缺少冻结 control/candidate/judge 时将模型行为报告为 `uncovered`。
