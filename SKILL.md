---
name: converge
description: "Implement/fix/refactor authorized work: 实现/修复/重构/按方案修改/修复已知问题/闭环完成. Excludes read-only review, autonomous continuation, multi-model execution, and multi-Batch."
metadata:
  compatibility: Requires Git and Python 3.9+; full-closure audits require CodeGraph. Install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge：单任务闭环执行

Converge 始终是 controller；规划/只读用 `converge-plan`、`converge-review`；见 `references/activation.md`。

需要持久状态的显式闭环使用 arm v11；终态只认新鲜证据。简单 `inline` 不创建 run。显式闭环先 arm 当前 workspace 的唯一 active run；active run 未到 `complete|blocked` 时不得输出 final。

## 开始

Skill 根目录记为 `CONVERGE_SKILL_DIR`。冻结验收、路径和基线，仅改 task diff；不可逆问用户。模型自述不放行；验收实检，`unknown` 失败，走完整路径。

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_engine.py" select --mode <auto|pdlc|native> --kind <feature|fix|refactor>
```

Provider Schema v2；pdlc-v1/native-v1，`engine` 只由 binding 派生，不能成为第二真相；见 [TDD](references/tdd-providers.md)、[控制](references/execution-control.md)。

## 路由

`planned_task=true` 仅执行 capsule；否则按 [任务路由](references/task-routing.md) 用 `task_profile.py [--full-closure]` 分类；持久状态用 `freeze_routing` 冻结画像与请求摘要。全量收口只能由控制器作出明确决定，不能由关键词猜测；`full_closure_required=true` 禁止 `inline`，且必须先经 `converge-plan`。自治续跑使用 `converge-autonomy`，多模型 runner 使用 `converge-multimodel`；两者虽默认可发现，仍只在用户明确要求时触发并冻结对应扩展，自治 Hook 还须显式启用。仅当路由不是 `inline`、需 worker/恢复或请求并发/无响应时，读 [计划执行与无响应保护](references/execution-control.md)。

按已选路径渐进读取引用：一次只读一个必要 reference，不得在单个命令中拼接多个完整协议。`inline` 或普通同会话计划不读 worker、恢复、自治或全量收口资料；只有实际进入对应路径时才读取其 contract。

没有宿主 bridge 时，原生子代理一律使用手工 capsule 交接；不得把 `spawn_agent`、wait timeout、消息投递或模型自述当作可恢复的 lifecycle 证据。只有具体宿主 bridge 完成无写入 smoke 并生成 `host_observed` tree-query Binding 后，才可走 worker registry 的自动 lifecycle。

复杂、未知或长任务用 `converge-plan`，按独立可验收的业务切片执行；仅 `cross_session` 进 `converge-batch` 并先获 commit 授权。全量收口必须先用 `converge-plan` 建矩阵，终态须当前源码的 closure gate；缺项标 `uncovered`，不得宣称全部完成；见 [Plan Contract](skills/converge-plan/references/plan-contract.md)。

## 终态

写入需 writer lease，原身份释放：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_lease.py" release --root <root> --repo <common-dir> --workspace <worktree> --task-key <task> --run-id <run> --writer-id <writer>
```

仅 `{"status":"released"}` 成功。按 [审查编排](references/review-orchestration.md) 复核；无进展停止，禁止删测试、降阈值或扩大范围造绿。

Plan v6 审计见 [Plan Contract](skills/converge-plan/references/plan-contract.md) 与 [状态](references/state-schema.md)。`delivery_report.py` 按 [交付回执](references/reporting.md) 输出交付轮数 / 修复问题数 / 待处理项；外发另行授权。Suite 改动用 `converge-eval`。
