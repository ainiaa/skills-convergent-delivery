---
name: converge-plan
description: Create and validate a finite software execution plan before implementation. Use for planning complex work, splitting a task into bounded steps, deciding sequential versus safe parallel execution, or preparing a plan for converge-batch. Do not use to modify business code, review a diff, or control PDLC internals.
metadata:
  compatibility: Requires Git and Python 3.9+; install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge Plan：有限执行计划

只负责把已授权需求变成可执行、可验证的有限计划。**不修改业务代码**、不做代码评审、不运行实现，也不拆解 PDLC 内部阶段。

先将本 `SKILL.md` 所在目录记为 `CONVERGE_PLAN_SKILL_DIR`。详细字段和完成审计读取 [Plan Contract v5](references/plan-contract.md)。

## 1. 冻结输入

记录需求、验收项、允许范围、基线、已有脏文件、公共契约和不可逆边界。先从代码、测试、项目文档和已有 ADR 查找答案；信息足够时直接规划。仍涉及业务规则、公共契约或不可逆选择时，按 [决策门禁](../../references/execution-control.md) 一次只提出一个带推荐、理由和影响的问题。除非用户明确把文档修改纳入范围，不因澄清自动创建或更新 `CONTEXT.md`、ADR 或其他项目文件。

## 2. 选择 planner provider

顺序固定：项目已有且仍有效的批准计划 → 已适配 Superpowers `writing-plans` → 通过安全预检的第三方计划 Skill → `native-plan-v1`。

- 第三方 provider 只提供拆解方法，不能接管实现、发布、删除、worktree 或循环控制。
- 选中第三方后记录绝对路径和内容摘要；恢复时变化则阻塞，不静默换 provider。
- 普通任务只使用一个 planner。仅高风险且确有两个冲突方案时，才让独立 arbiter 比较验收覆盖、风险和可逆性。

## 3. 形成 Plan Contract

- 每个任务用 `task_kind=vertical_slice|wide_refactor|integration` 明确类型，并在 `outcomes` 中只声明一个可独立验证的结果；多个独立结果必须拆成多个垂直切片。
- `integration` 必须依赖至少一个前置任务；`wide_refactor` 只表示一个外部行为不变但路径较宽的结果。
- 每个 step 只描述一个动作；不得把“文档 + 测试 + 实现 + review”塞进一步。
- 明确 `owned_paths`、`depends_on`、验收行为和真实验证命令。
- 简单任务仍可只有一个 task，不为它增加虚构阶段。
- 每个 task 冻结自己的 Provider Binding，并声明 `provider_run={scope: task, recursive_planning: false}`。PDLC 仍完整负责一个 task 内部阶段，但一个计划可以包含多个边界独立、可分别验收的 PDLC-backed task。
- Plan v5 的 `decisions` 只记录结构化已决事项；任何业务、公共契约、权限、发布或不可逆问题尚未解决时，不生成可执行计划。

将完整 JSON 经 stdin 校验：

```bash
python3 "$CONVERGE_PLAN_SKILL_DIR/scripts/plan_check.py" validate --input -
```

校验失败时修正一次；仍失败则停止，不把无效计划交给执行器。

## 4. 选择执行方式

以 helper 输出为准：

- `current`：单个短任务，当前上下文仍清晰。
- `fresh`：PDLC、单个复杂任务或当前上下文已长/压缩。
- `sequential`：`checkpoint=same_session` 的多个任务由同一会话按 wave 顺序执行，不要求本地 commit 授权。
- `batch`：只有确需跨会话恢复时才设 `checkpoint=cross_session` 并交给 `converge-batch`；此时 helper 输出 `commit_authorization_required=true`，控制器必须在 checkpoint 前单独请求一次本地 commit 授权。wave 仍只标识依赖和潜在并行候选。

所有派发 capsule 写入 `planned_task=true`、`plan_id`、`task_id`、Provider Binding、冻结范围和验收。执行者看到 `planned_task=true` 后只执行该 task，不再次规划。

## 5. 交接

输出计划路径或完整 JSON、校验结果、执行方式和第一个可执行 task。不得自行开始实现。同会话多任务顺序交给 `converge`；只有显式跨会话 checkpoint 的计划交给 `converge-batch`。
