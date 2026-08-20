---
name: converge-plan
description: Create and validate a finite software execution plan before implementation. Use for planning complex work, splitting a task into bounded steps, deciding sequential versus safe parallel execution, or preparing a plan for converge-batch. Do not use to modify business code, review a diff, or control PDLC internals.
---

# Converge Plan：有限执行计划

只负责把已授权需求变成可执行、可验证的有限计划。**不修改业务代码**、不做代码评审、不运行实现，也不拆解 PDLC 内部阶段。

先将本 `SKILL.md` 所在目录记为 `CONVERGE_PLAN_SKILL_DIR`。详细字段和完成审计读取 [Plan Contract v2](references/plan-contract.md)。

## 1. 冻结输入

记录需求、验收项、允许范围、基线、已有脏文件、公共契约和不可逆边界。信息足够时直接规划；涉及业务规则、公共契约或不可逆选择时，按 [决策门禁](../../references/execution-control.md) 一次只提出一个带推荐的问题。

## 2. 选择 planner provider

顺序固定：项目已有且仍有效的批准计划 → 已适配 Superpowers `writing-plans` → 通过安全预检的第三方计划 Skill → `native-plan-v1`。

- 第三方 provider 只提供拆解方法，不能接管实现、发布、删除、worktree 或循环控制。
- 选中第三方后记录绝对路径和内容摘要；恢复时变化则阻塞，不静默换 provider。
- 普通任务只使用一个 planner。仅高风险且确有两个冲突方案时，才让独立 arbiter 比较验收覆盖、风险和可逆性。

## 3. 形成 Plan Contract

- 每个任务只交付一个可独立验证的结果。
- 每个 step 只描述一个动作；不得把“文档 + 测试 + 实现 + review”塞进一步。
- 明确 `owned_paths`、`depends_on`、验收行为和真实验证命令。
- 简单任务仍可只有一个 task，不为它增加虚构阶段。
- 每个 task 冻结自己的 Provider Binding，并声明 `provider_run={scope: task, recursive_planning: false}`。PDLC 仍完整负责一个 task 内部阶段，但一个计划可以包含多个边界独立、可分别验收的 PDLC-backed task。

将完整 JSON 经 stdin 校验：

```bash
python3 "$CONVERGE_PLAN_SKILL_DIR/scripts/plan_check.py" validate --input -
```

校验失败时修正一次；仍失败则停止，不把无效计划交给执行器。

## 4. 选择执行方式

以 helper 输出为准：

- `current`：单个短任务，当前上下文仍清晰。
- `fresh`：PDLC、单个复杂任务或当前上下文已长/压缩。
- `batch`：多个任务交给 `converge-batch`。wave 用于标识依赖和潜在并行候选；内置 Batch Protocol v1 仍按原顺序执行，避免多 worktree 集成和 receipt 无法可靠恢复。

所有派发 capsule 写入 `planned_task=true`、`plan_id`、`task_id`、Provider Binding、冻结范围和验收。执行者看到 `planned_task=true` 后只执行该 task，不再次规划。

## 5. 交接

输出计划路径或完整 JSON、校验结果、执行方式和第一个可执行 task。不得自行开始实现。长计划交给 `converge-batch`，单任务交给 `converge`。
