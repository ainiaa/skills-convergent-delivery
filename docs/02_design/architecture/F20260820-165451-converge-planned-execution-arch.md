<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-165451 -->
<!-- 功能名称: converge-planned-execution -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260820-165451-converge-planned-execution-prd.md -->

# 架构设计：Converge 计划化执行

> 文档编号：ADR-202608-001  
> 创建日期：2026-08-20  
> 作者：Jeff.Liu  
> 状态：已评审

## 1. 目标与非目标

目标是把“长时间在一个模型步骤内准备全部产物”改成“计划 → 短任务执行 → 对账”，同时保持既有 Skill 的单一职责。非目标是重写 PDLC、实现通用工作流引擎或强制所有小改动创建复杂计划。

## 2. Suite 职责

| 组件 | 唯一职责 | 明确不做 |
|---|---|---|
| `converge-plan` | 形成、校验有限执行计划，记录必要决策 | 改代码、跑实现、review、控制 PDLC 内部阶段 |
| `converge` | 完成一个冻结任务并有限收敛 | 调度长计划、复制 PDLC/TDD 状态机 |
| `converge-batch` | 根据已校验计划派发多个独立任务并验收回执 | 设计方案、读业务代码、亲自实现 |
| `converge-review` | 独立只读审查 | 修复代码或改变任务范围 |

## 3. 控制流

```text
冻结需求 → 选择实现引擎
              ├─ pdlc-v1 → 单任务计划(pdlc-run) → 全新上下文整体执行 PDLC
              └─ other   → converge-plan → 校验计划
                                             ├─ 单个短任务 → 当前上下文
                                             ├─ 单个复杂/长上下文任务 → 全新上下文
                                             └─ 多任务 → converge-batch（v1 顺序执行）
执行 → 验证 → 计划/差异/证据对账 → 有限修复 → 最终报告
```

PDLC 委托屏障要求：选择 `pdlc-v1` 后，Converge 只创建一个 `pdlc-run` 任务，并立即委托完整 `pdlc-feature` 或 `pdlc-fix`。不得在主上下文预生成 PDLC 文档、native TDD 或阶段 review。

## 4. Plan Contract v1

计划使用 JSON 表示，便于状态冻结和确定性检查：

```json
{
  "schema_version": 1,
  "plan_id": "plan-...",
  "requirement_fingerprint": "sha256",
  "engine": "pdlc-v1|...",
  "planner": {"name": "native-plan-v1", "source_path": null, "source_fingerprint": null},
  "context": "short|long",
  "tasks": [
    {
      "task_id": "T1",
      "goal": "一个可独立验证的结果",
      "owned_paths": ["path/or/prefix"],
      "depends_on": [],
      "steps": ["一次动作"],
      "acceptance": ["可观察行为"],
      "verification": ["真实命令"],
      "execution": "auto|current|fresh",
      "status": "pending"
    }
  ],
  "final_acceptance": ["整体集成验收"],
  "decisions": []
}
```

`plan_check.py validate` 校验必填字段、哈希、唯一任务 ID、依赖存在、无循环；按依赖和 `owned_paths` 生成执行 wave。无依赖但路径重叠的任务不能位于同一 wave。`pdlc-v1` 只接受唯一 `pdlc-run` 任务。

`planned_task=true` 是递归保护：接到 capsule 的执行者只执行冻结任务，不再调用 `converge-plan` 或创建子计划。Batch Schema 同时校验 `plan_id/task_id` 与冻结映射，避免该保护只停留在提示词。

## 5. 计划提供者与仲裁

非 PDLC 路径按以下顺序选择：项目已有已批准计划 → 已适配 Superpowers `writing-plans` → 通过安全预检的第三方计划 Skill → Converge 原生最小计划。选中后冻结来源路径和摘要；恢复时变化则阻塞。

只有同时满足“高风险、存在两个实质冲突方案、差异会影响公共契约或不可逆结果”时才使用计划仲裁。普通任务由单个计划者完成，避免额外轮次。

## 6. 决策门禁

| 类别 | 处理 |
|---|---|
| 技术且可逆 | 自动采用项目既有模式并记录 |
| 局部且有明确推荐 | 自动采用推荐默认并记录 |
| 业务规则、公共契约、发布或不可逆 | 一次只询问最高优先级问题，附推荐和影响 |

## 7. 无响应与恢复

本节是 Runtime Adapter 在宿主具备计时、活动/进程查询、中断和恢复 API 时的行为约束；Skill 文本本身不实现后台 watchdog。能力不全时只允许保存 capsule/receipt 并手工交接，不得宣称已中断或自动恢复。

- 软探测：约 90 秒内没有 commentary、工具调用、状态、diff 或 worker 回执，且没有运行进程时，输出进度并检查原任务。
- 硬中断：约 180 秒仍满足全部无活动条件时才中断当前生成；保存任务/计划项引用，最多自动恢复一次。
- 恢复必须查询同一 `worker_ref` 或继续同一 `plan_id/task_id`，不能重新派发。
- Batch Protocol 保持 v1，state Schema v2 持久化 `worker_ref/recovery_count`，并允许旧 v1 先做身份字段迁移；恢复计数最多为 1。`repo_id + plan_id` scheduler lease 默认两小时、随写入续期，活动 owner 不可抢占，过期后仅显式 takeover；它不替代 worker writer lease。
- 有真实测试、构建、PDLC 或子任务进程运行时只等待并汇报，不中断。

## 8. 完成审计

计划结束时，对每项任务输出 `DONE`、`PARTIAL`、`NOT_DONE` 或 `CHANGED`；audit 从真实 workspace 自行读取 Git commit/tree/diff/changed paths，每个 `DONE` 必须携带绑定该 source receipt 的结构化通过证据。receipt 中的命令文本不由 audit 执行。计划外 diff 标记 `scope_drift`。存在 P0 验收未完成、证据陈旧或未授权漂移时不得交付。

## 9. 风险与控制

| 风险 | 控制 |
|---|---|
| 计划本身过重 | 单任务低风险只生成一项短计划；PDLC 只有一个委托任务 |
| 并行写冲突 | wave 只标识候选；Batch v1 顺序执行，不伪造多 worktree 集成能力 |
| 恢复导致重复执行 | 保存并查询原 worker；不确定即阻塞 |
| 第三方 Skill 漂移 | 冻结来源摘要，恢复时重新校验 |
| 看似完成但有遗漏 | 计划、diff、验收证据三方对账 |

## 10. 自审记录

- PRD P0/P1 覆盖：8/8。
- 跨组件职责、PDLC 边界、并发、恢复和停止条件检查：5/5 通过。
- 未引入新依赖；复用现有 lease、Batch Runtime Adapter 和报告协议。
