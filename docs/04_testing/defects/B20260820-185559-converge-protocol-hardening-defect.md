<!-- PDLC-TRACE -->
<!-- 功能ID: B20260820-185559 -->
<!-- 功能名称: converge-protocol-hardening -->
<!-- 阶段: review -->
<!-- 前置文档: docs/02_design/architecture/F20260820-165451-converge-planned-execution-arch.md -->
<!-- 创建时间: 2026-08-20T19:10:52+08:00 -->
<!-- 关系: extends=F20260820-165451 -->

# 缺陷记录：Converge 协议加固

作者：Jeff.Liu

## 根因分析

单任务 state helper 只校验候选 JSON 自身和 revision，没有对前后状态做契约、阶段与 ledger 单调性校验；Batch capsule 的递归规划保护只写在 Skill 文本中，Schema 没有绑定 `planned_task/plan_id/task_id`；Plan audit 直接采用调用者填写的源码指纹和 changed paths；Batch state 又按 `run_id` 分路，没有以计划身份互斥调度者。watchdog 文档同时混淆了 Skill 规则与宿主真正暴露的计时、中断和恢复 API。

## 影响范围

- 单任务跨窗口恢复可能改写 baseline、scope、engine、阶段或历史证据，并可能绕过正式 workspace lease move。
- 错误 Batch capsule 可能让执行者再次规划；同一计划可能被两个 run/window 重复派发。
- 陈旧或伪造的 source fingerprint/changed paths 可能让完成审计漏报证据陈旧和范围漂移。
- 能力不足的宿主可能被文档误导为已经自动执行 watchdog 中断或 PDLC 恢复。

## 修复方案

- `delivery_state.py` 冻结 repo/task/run/writer/baseline/scope/engine，限制原生与 PDLC 阶段合法前进，保持 repair/checks/history 追加和 round 单步递增；acceptance 当前事实可回归，但必须归档旧 revision，criterion 不变且完成态仍严格。终态字段对称冻结；workspace 变化必须匹配 lease record，合法 `move` 继续可用。
- Batch Protocol 保持 v1，state Schema 升为 v2 并可从真实旧 v1 做只添加身份字段的原子迁移。v2 强制 capsule 的 `planned_task=true`、匹配的 `plan_id/task_id`，持久化 `worker_ref/recovery_count`，并以 `repo_id + plan_id` 建立默认两小时、每次写入续期、仅过期后显式接管的 scheduler lease；worker 代码写权仍由 `$converge` writer lease 管理。
- `plan_check.py audit` 要求真实 `--workspace`，只运行固定且禁用 external diff/textconv 的只读 Git 子命令，自行绑定 HEAD commit/tree、diff、未跟踪文件和 Git 原生 changed paths；反斜杠文件名不会改写为 `/`。任务与计划级证据绑定同一 source 的结构化 receipt，receipt 中的命令文本不会执行。
- 同步 Plan Contract、Batch Contract、状态 Schema、Runtime Adapter、README、使用指南、设计说明、CHANGELOG 和版本元数据；保持 Batch Protocol v1 顺序执行。

## 回归测试覆盖

- 正常：合法阶段/终态、追加证据、正式 workspace lease move、单一 scheduler、当前 source receipt、一次 worker 恢复。
- 边界：completed rounds 单步递增、recovery count 上限为 1、未跟踪文件参与 source fingerprint。
- 异常：冻结字段改写、阶段回退/跳跃、ledger 删除或篡改、终态改写、未 move 的 workspace 变化、错误 capsule 身份、第二个 scheduler、陈旧/伪造 source、范围漂移和任意命令文本。
- 全量结果：`bash scripts/check.sh` 通过，123 个测试、0 个失败。
- 安装诊断：`bash install.sh --doctor --target codex --offline` 通过，Suite `0.9.1` complete。

## Blind review finding closure

| Finding 指纹 | Closure 证据 |
|---|---|
| `single-state/acceptance-freshness/pass-fresh-to-stale-or-fail-rejected-by-rank` | `test_应该_当状态合法前进时_保留追加证据并允许工作区迁移` 分别验证 pass/fresh→pass/stale 与 pass/stale→fail/fresh，旧值和 revision 追加到 history。 |
| `single-state/terminal-immutability/missing-terminal-fields-escape-asymmetric-comparison` | `test_应该_当终态候选删除字段时_对称比较并拒绝` 和 `test_应该_当终态缺少阶段必需字段时_拒绝恢复` 覆盖回写与 complete/blocked 恢复。 |
| `batch-state/schema-v1-upgrade/preexisting-v1-capsule-and-task-fields-unreadable` | `test_应该_当恢复真实旧v1状态时_迁移到新Schema并继续` 从无 identity/recovery 字段的真实旧形状迁移到 Schema v2，并拒绝新建 v1。 |
| `batch-scheduler/lease-lifecycle/crash-between-owner-record-and-state-causes-permanent-lock` | `test_应该_当调度租约已过期且状态未落盘时_允许显式接管` 覆盖 crash window；`test_应该_当同一计划已有调度者时_拒绝第二个运行窗口` 覆盖活动 owner 即使 takeover 也拒绝。 |
| `plan-audit/git-path-boundary/backslash-filename-normalized-to-owned-slash-path` | `test_应该_当Git文件名包含反斜杠时_不归一化为已授权斜杠路径` 使用真实 `src\evil` 文件并确认其仍列入 scope drift。 |

## 假设与说明

- scheduler lease 默认两小时并随状态写入续期；活动 owner 不可抢占，过期 owner 仅在确认已停止后显式 takeover。
- Batch Protocol v1 继续顺序执行；未实现并行 Batch、多 worktree 自动集成或宿主插件。
- 官方 `quick_validate.py` 已实际运行，但当前 Python 3.14.4 环境缺少 `PyYAML`，报 `ModuleNotFoundError: No module named 'yaml'`。按任务约束未安装新依赖，因此该项无法完成；仓库自带 Skill/installer 检查均已通过。

## 上线前待办

- 无代码或数据迁移待办。
- 若发布环境要求官方 validator 结果，需由维护者在已提供 PyYAML 的隔离环境中重跑；本次不安装、不发布、不提交、不打 tag。
