---
name: converge
description: "Implement/fix/refactor authorized work: 实现/修复/重构/按方案修改/修复已知问题/闭环完成. Excludes read-only review and multi-Batch."
metadata:
  compatibility: Requires Git and Python 3.9+; install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge：单任务闭环执行

Converge 始终是 controller；规划、只读、跨会话用 `converge-plan`、`converge-review`、`converge-batch`。触发：[激活](references/activation.md)。

持久/跨会话/Suite 改动：从 `CONVERGE_SKILL_DIR` 解析，先快照，见 [状态 Schema](references/state-schema.md)。

## 开始

冻结验收/路径/基线/行为，仅改本 task diff；授权不扩大，不可逆选择问用户。验收须实检；`unknown` 失败，行为改动须回归。fast path 停用，走完整路径。

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_engine.py" select --mode <auto|pdlc|native> --kind <feature|fix|refactor>
```

Provider Schema v2 binding；`engine` 仅由 binding 派生，不能成为第二真相。Provider 规则见 [TDD 提供者](references/tdd-providers.md)；`pdlc-v1`、`native-v1` 的 task 内部仍整体委托。

## 路由

`planned_task=true` 仅执行 capsule；否则按 [任务路由](references/task-routing.md) 用 `task_profile.py` 冻结画像。仅当路由不是 `inline`、需 worker/恢复或请求并发/无响应时，读 [计划执行与无响应保护](references/execution-control.md)。

复杂/未知/长任务用 `converge-plan`，按独立可验收的业务切片执行；仅 `cross_session` 进 `converge-batch` 并先获 commit 授权，见 [Plan Contract](skills/converge-plan/references/plan-contract.md)。

worker 用当前会话真实能力；跨会话需 `host_observed` bridge，缺能力手工交接，见 [Runtime Adapters](skills/converge-batch/references/runtime-adapters.md)。

## 终态

写入需 writer lease，原身份释放：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_lease.py" release --root <root> --repo <common-dir> --workspace <worktree> --task-key <task> --run-id <run> --writer-id <writer>
```

仅 `{"status":"released"}` 成功。按 [审查编排](references/review-orchestration.md) 复核；无进展停止，禁止删测试、降阈值或扩大范围造绿。

Plan 审计见 [Plan Contract](skills/converge-plan/references/plan-contract.md) 与 [状态 Schema](references/state-schema.md)。`delivery_report.py` 按 [交付回执](references/reporting.md) 输出交付轮数 / 修复问题数 / 待处理项；外发另行授权。Suite 改动用 `converge-eval` 按 [压力场景](references/evaluation-scenarios.md) 评估。
