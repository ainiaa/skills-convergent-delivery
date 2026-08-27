---
name: converge
description: "Implement/fix/refactor authorized work: 实现/修复/重构/按方案修改/修复已知问题/使用多模型配合开发/闭环完成. Excludes read-only review and multi-Batch."
metadata:
  compatibility: Requires Git and Python 3.9+; install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge：单任务闭环执行

Converge 始终是 controller；规划/只读用 `converge-plan`、`converge-review`；见 `references/activation.md`。

闭环 arm v11；终态只认新鲜证据。显式闭环先 arm 当前 workspace 的唯一 active run；active run 未到 `complete|blocked` 时不得输出 final。

## 开始

Skill 根目录记为 `CONVERGE_SKILL_DIR`。冻结验收/路径/基线，仅改 task diff；不可逆问用户。模型自述不放行；验收实检，`unknown`失败，走完整路径。

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_engine.py" select --mode <auto|pdlc|native> --kind <feature|fix|refactor>
```

Provider Schema v2；pdlc-v1/native-v1，`engine` 只由 binding 派生，不能成为第二真相；见 [TDD](references/tdd-providers.md)、[控制](references/execution-control.md)。

## 路由

`planned_task=true` 仅执行 capsule；否则按 [任务路由](references/task-routing.md) 用 `task_profile.py --request-file <raw-request>` 冻结画像；`full_closure_required=true` 禁止 `inline`。仅当路由不是 `inline`、需 worker/恢复或请求并发/无响应时，读 [计划执行与无响应保护](references/execution-control.md)。

复杂、未知或长任务用 `converge-plan`，按独立可验收的业务切片执行；仅 `cross_session` 进 `converge-batch` 并先获 commit 授权。全量收口必须先用 `converge-plan` 建矩阵，终态须当前源码的 closure gate；缺项标 `uncovered`，不得宣称全部完成；见 [Plan Contract](skills/converge-plan/references/plan-contract.md)。

## 终态

写入需 writer lease，原身份释放：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_lease.py" release --root <root> --repo <common-dir> --workspace <worktree> --task-key <task> --run-id <run> --writer-id <writer>
```

仅 `{"status":"released"}` 成功。按 [审查编排](references/review-orchestration.md) 复核；无进展停止，禁止删测试、降阈值或扩大范围造绿。

Plan v6 审计见 [Plan Contract](skills/converge-plan/references/plan-contract.md) 与 [状态](references/state-schema.md)。`delivery_report.py` 按 [交付回执](references/reporting.md) 输出交付轮数 / 修复问题数 / 待处理项；外发另行授权。Suite 改动用 `converge-eval`。
