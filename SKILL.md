---
name: converge
description: "Implement/fix/refactor authorized work: 实现/修复/重构/按方案修改/修复已知问题/闭环完成. Excludes standalone read-only review, autonomous continuation, multi-model execution, and multi-Batch."
metadata:
  compatibility: Requires Git and Python 3.9+; native runtime tasks require an indexed CodeGraph CLI and configured coverage; full-closure audits also require CodeGraph. Install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge：单任务闭环执行

Converge 始终是 controller，负责同一会话内已授权的软件交付；规划用 `converge-plan`，独立只读审查用 `converge-review`。触发见 [激活](references/activation.md)。

## 每轮约束

- 同一会话的写入授权持续有效，直到用户明确“仅审查/不要修改”、停止、取消，或提出范围外的新目标。
- 已授权写入任务中的审查是只读检查点：审查本身不写入；完成后，同范围 finding 自动修复并验证。范围外 finding 只记录影响并一次提出所需决定。
- 先从当前任务、代码、测试和已决事项取得答案；不重复询问。只在业务规则、公共兼容、权限、发布或不可逆操作需要决定时提问，并给出一个推荐。
- 每个 finding 必须是修复、阻塞决策或范围外记录之一；不以建议替代同范围闭环。
- 模型自述不放行。没有本轮真实验证的验收不得称完成；命令不可用、超时或权限不足为 `uncovered`，不得放松检查取得通过。
- 按需读取 reference：简单 `inline` 只读路由、TDD 和报告；计划、跨会话、自治、多模型或全量收口才读对应 contract。

用户要求“逐步修复 / 分步执行 / 按计划一步步做”时，每步开始与结束各用一条独立的 commentary 消息，结束不得与下一步开始合并；原生计划工具不可用时明确文字降级，不把文字说成原生面板。

## 开始与验证

将本目录记为 `CONVERGE_SKILL_DIR`。先按 [任务路由](references/task-routing.md) 分类，冻结验收、范围和基线，只改任务 diff；外发和不可逆操作单独询问。简单 `inline` 不运行 `delivery_engine.py select`，直接按 TDD 追溯完成局部红绿和报告。运行时功能、修复和重构先写可执行测试，再改生产代码；完整 red/green、影响、覆盖率和 Provider 规则见 [TDD 追溯](references/tdd-providers.md#tddimpact-trace-v5)。

仅 `planned`、`delegated`、`batch` 路由或用户明确要求 Provider binding 时选择并冻结 Provider：
```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_engine.py" select --mode <auto|pdlc|native> --kind <feature|fix|refactor>
```

Provider 选择冻结为 `native-v1` 或 `pdlc-v1`；native-v1 在首次业务写入前执行 `tdd_impact_guard.py preflight`，最终使用其 `rerun` 绑定当前源码。没有 CodeGraph、coverage 或可执行检查时保持 `uncovered`，不安装、不建索引、不降门槛。修改 Converge Suite 时更新本仓 `CHANGELOG.md` 的 `Unreleased`；目标项目的写入任务按其约定更新 changelog。

## 路由与终态

`planned_task=true` 只执行冻结 capsule。复杂、未知或长任务先用 `converge-plan`；只有明确跨会话 checkpoint 才用 `converge-batch`。全量收口必须显式选择并使用 Plan matrix，不能由关键词推断。

持久状态使用既有 writer lease，并按 [执行协议](references/execution-protocol.md) 和 [状态](references/state-schema.md) 清场。 风险等级对应的复核边界见 [审查编排](references/review-orchestration.md)。没有真实宿主 bridge 时，不把本地 state、capsule、子任务或模型自述称为自动续跑、完成或清场证据。

最终按 [交付回执](references/reporting.md) 只报告当前证据能证明的范围；确定性回归、真实宿主 smoke 和模型成本分别说明。外发另行授权；Suite 行为改动完成后使用 `converge-eval`。
