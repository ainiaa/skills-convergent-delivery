<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-102230 -->
<!-- 功能名称: plan-granularity -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260821-102230-plan-granularity-prd.md -->
<!-- 创建时间: 2026-08-21T10:24:23+08:00 -->

# Plan Granularity 架构设计

## 1. 背景与目标

`plan_check.py` 已能校验依赖、范围、Provider Binding 和 evidence，但任务粒度只存在于自由文本，且 `len(tasks) > 1` 无条件路由到 Batch。本设计以最少字段让粒度和跨会话连续性可确定性校验。

## 2. 契约设计

### 2.1 Schema v3

每个新 task 增加：

```json
{
  "task_kind": "vertical_slice | wide_refactor | integration",
  "outcomes": ["one independently verifiable result"]
}
```

- `outcomes` 必须恰好一个；两个或更多表示独立结果尚未拆分，直接返回包含 task id 和拆分动作的错误。
- `integration` 必须至少依赖一个前置 task；它只交付跨切片集成结果。
- `wide_refactor` 表示一个跨较宽路径但外部行为不变的结果，不是多个功能的容器。
- 不使用 goal 关键词或 acceptance 数量推断结果边界。

计划顶层增加：

```json
{"checkpoint": "same_session | cross_session"}
```

`same_session` 表示同一控制器上下文持续顺序执行；`cross_session` 表示需要 Batch checkpoint 和恢复基线。

### 2.2 旧 schema 迁移

- schema v1 先沿用已有 Provider Binding 迁移，再进入 v2→v3 粒度迁移。
- 短上下文单任务和多任务可从每个 task 的 `goal` 推导单 outcome，task kind 默认 `vertical_slice`，checkpoint 默认 `same_session`。
- long context 单任务无法证明只有一个结果，迁移必须阻塞并提示升级 schema v3、声明类型/单 outcome，或拆分为多个垂直切片。

该限制只针对无法证明粒度的旧 long 单任务；显式 schema v3 long 单任务继续通过。

## 3. 执行路由

```text
validated plan
  ├─ checkpoint=cross_session → batch + commit_authorization_required=true
  ├─ tasks > 1                → sequential + false
  ├─ PDLC / explicit fresh    → fresh + false
  └─ short auto               → current + false
```

wave 计算保持不变：依赖和 owned path 重叠仍决定顺序。`sequential` 仅修正控制方式，不宣称并行。

## 4. 模块变更

| 文件 | 变更 |
|---|---|
| `scripts/plan_check.py` | schema v3 迁移、类型/结果校验、checkpoint 路由 |
| `scripts/test_plan_check.py` | 正常、边界、异常和兼容回归 |
| `SKILL.md` | 计划形成和执行选择规则 |
| `references/plan-contract.md` | Plan Contract v3 字段与 commit 授权边界 |

无需 API、数据库、依赖或新 helper。

## 5. 验证设计

| 验收 | 测试 |
|---|---|
| 三种 task kind | 参数化通过测试 + 未知 kind 失败测试 |
| 多 outcomes 阻塞 | long context 两 outcomes，断言结构化 stderr |
| 真单结果通过 | long schema v3 vertical slice |
| 有依赖多任务通过 | vertical slice → integration waves |
| integration 依赖 | 无依赖失败、有依赖通过 |
| 同会话无 commit | 多任务输出 sequential/false |
| 跨会话才 commit | cross_session 输出 batch/true |
| 旧 long 单任务 | schema v2 返回可操作升级/拆分原因 |

## 6. 风险与决策

- 风险：schema 迁移自动把旧多任务视为多个切片，不能补出精确 kind。决策：保留兼容但 normalized schema 为 v3；所有新计划必须显式声明。
- 风险：同会话执行可能经历意外进程中断。决策：未获 commit 授权时不伪造可恢复 checkpoint；需要恢复时由控制器显式选择 cross_session 并请求授权。
- 决策：不修改 Batch helper；它继续只处理真正的 cross-session batch。

## 7. 自审记录

- PRD P0/P1 覆盖：7/7。
- API/DB：不涉及，跳过。
- 边界：多 outcome、未知 kind、integration 无依赖、旧 long 单任务均有明确失败路径。
- 权限：不会创建 commit；授权只作为计划输出布尔值，由 Batch 控制器请求。
- 一次复查：0 个未解决问题。
