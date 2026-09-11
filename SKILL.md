---
name: converge
description: "Implement/fix/refactor authorized work: 实现/修复/重构/按方案修改/修复已知问题/闭环完成. Multi-model external runners require the explicit converge-multimodel extension; excludes standalone read-only review, autonomous continuation, and multi-Batch."
metadata:
  compatibility: Requires Git and Python 3.11+; native runtime tasks require an indexed CodeGraph CLI and configured coverage; full-closure audits also require CodeGraph. Install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge：单任务闭环执行

Converge 始终是 controller，负责同一会话内已授权的软件交付；规划用 `converge-plan`，独立只读审查用 `converge-review`。触发见 [激活](references/activation.md)。

## 每轮约束

- 同一会话的写入授权持续有效，直到用户明确“仅审查/不要修改”、停止、取消，或提出范围外的新目标。
- 已授权写入任务中的审查是只读检查点：审查本身不写入；完成后，同范围 finding 自动修复并验证。范围外 finding 只记录影响并一次提出所需决定。
- 先从当前任务、代码、测试和已决事项取得答案；不重复询问。只在业务规则、公共兼容、权限、发布或不可逆操作需要决定时提问，并给出一个推荐。
- 每个 finding 必须是修复、阻塞决策或范围外记录之一；不以建议替代同范围闭环。
- 模型自述不放行。没有本轮真实验证的验收不得称完成；命令不可用、超时或权限不足为 `uncovered`，不得放松检查取得通过。
- 用户明确指定为实现依据的引用（包括 `codex://`）是需求真源，不是背景提示。首次业务写入前必须通过当前宿主实际读取，并据此冻结范围与验收；不得未读参考就猜测实现，或用另一套行为替代。若引用未规定内部细节，沿用项目既有模式作最小选择；若其对完成需求必需但不可访问则阻塞。普通背景链接不构成门禁；持久化任务记录精确 reference 与读取结果，`inline` 任务在交付中说明已读取。
- 一个用户任务必须在当前 task 内完成其有限的构建、全范围复审、修复批和最终复核；Stop Hook 不得排队 successor task 或以无用户消息的额外 task turn 重新开启审查。
- 按需读取 reference：简单 `inline` 只读路由、TDD 和报告，其中 TDD 先读 [Inline TDD](references/inline-tdd.md)；计划、跨会话、自治、多模型或全量收口才读对应 contract。

用户要求“逐步修复 / 分步执行 / 按计划一步步做”时，每步开始与结束各用一条独立的 commentary 消息，结束不得与下一步开始合并。完成消息发送后，必须先结束该 commentary；下一步的开始只能在随后新的 commentary 中发送。不得在完成消息中声明、计划或调用下一步的动作；任何用于下一步的计划更新或工具调用，都只能放在该开始消息之后。原生计划工具可用时，每个步骤边界都必须调用一次原生计划工具：初始创建后，每次完成消息之后先将当前项更新为 completed，每次下一步开始 commentary 之后立即调用，将该项更新为 in_progress；同一次原生调用不得同时覆盖前一步完成和下一步开始。不得只在初始建表或最终收口时批量更新，也不得在对应调用成功前执行下一步工具。原生计划工具不可用时明确文字降级，不把文字说成原生面板。

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

对已落盘事项，验证必须通过 `work_item.py verify` 执行；它只接受事项冻结的 workspace/baseline，先 gate、再由 `evidence_contract` 取得 observed Evidence Receipt，并在失败时原子记录。不得直接运行冻结 verifier argv。相同源码与 argv 的失败返回 `blocked`，不得重复执行；只有源码、argv 或通过 `--recovery-receipt` 提供的同一源码 observed pass 回执才可重试。完成仍须现有的最终新鲜 `pass` 证据，不得把恢复回执或模型自述当作完成。

持久状态使用既有 writer lease，并按 [执行协议](references/execution-protocol.md) 和 [状态](references/state-schema.md) 清场。风险等级对应的复核边界见 [审查编排](references/review-orchestration.md)；Desktop、CLI 与 subagent 的可证明边界见 [宿主能力](references/host-capabilities.md)。没有真实宿主 bridge 时，不把本地 state、capsule、子任务或模型自述称为自动续跑、完成或清场证据。

最终按 [交付回执](references/reporting.md) 只报告当前证据能证明的范围；确定性回归、真实宿主 smoke 和模型成本分别说明。外发另行授权；Suite 行为改动先运行 `converge-eval` 的 deterministic preflight，缺少冻结 control/candidate/judge 时将模型行为报告为 `uncovered`。
