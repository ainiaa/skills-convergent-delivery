<!-- PDLC-TRACE -->
<!-- 功能ID: B20260820-200236 -->
<!-- 功能名称: worker-lifecycle-hardening -->
<!-- 阶段: review -->
<!-- 前置文档: docs/02_design/architecture/F20260820-165451-converge-planned-execution-arch.md -->
<!-- 创建时间: 2026-08-20T20:11:52+08:00 -->
<!-- 关系: extends=F20260820-165451 -->

# 缺陷记录：Worker 生命周期加固

作者：Jeff.Liu

## 根因分析

Suite 已要求保存 Batch `worker_ref`，但没有覆盖 PDLC、reviewer、辅助分析和独立前向测试的统一 run-scoped 登记表，也没有在全部退出路径设置宿主终态清场屏障。Batch helper 只验证 receipt 和 Git 证据，未验证同一宿主 worker 是否已经结束；Schema v3 首版还只校验 lifecycle 字段完整性，没有把它们绑定到 Batch phase，因此未来 pending Batch 可以提前登记 active worker。

## 影响范围

- 当前任务新建的 worker 可能在主执行者正常完成、异常、用户中断、`no_progress` 或验证失败后仍保持 active。
- 父执行者若依赖全局列表猜测归属，可能误操作用户或其他任务的 worker。
- Batch receipt 可早于宿主终态，后续 Batch 可能在上一 worker 仍 Working 时开始。
- 独立前向测试按场景创建多个 evaluator 会放大遗留 worker 数量。

## 修复方案

- 为所有委托定义 run-scoped worker registry：宿主返回后第一动作登记稳定 ref、role、owner run 和 working 状态；没有稳定可查询 ref 时只允许手工交接。
- 所有退出路径执行等价 `finally`，只查询/等待/中断本 run 的精确 ref；自然语言回执不替代宿主 `completed|interrupted|blocked`。无法 query/interrupt 时返回 blocked/manual cleanup。
- Batch state 升级为 Schema v3，新增 `worker_role/worker_owner_run_id/worker_status`，支持旧 v1/v2 只添加字段迁移；Batch completed 强制要求同一 worker 的宿主状态为 completed。
- Schema v3 进一步限定 pending/dispatching 不得持有 worker lifecycle；宿主返回 ref 后必须在同一 revision 进入 running 并登记完整 lifecycle。
- `batch_next.py` 在 receipt 已到但 worker 仍 working 时继续查询原 ref，不放行下一批。
- 独立前向测试默认只使用一个 evaluator，在隔离临时工作区顺序执行相关有限场景，结束前确认本轮 active worker 数为 0。

## 回归测试覆盖

- 正常：worker 创建后原子登记身份、归属和 working 状态；宿主 completed 后完成 Batch；旧 v1/v2 的 pending、dispatching 和 running 状态迁移到 v3。
- 边界：receipt 已到但宿主仍 working 时继续 query；单 evaluator 顺序评估契约。
- 异常：缺少角色、owner 不匹配、pending/dispatching 提前拥有 lifecycle、未来 Batch 提前登记 active worker、active worker 尝试完成 Batch、无稳定 ref、历史孤儿不可见。
- 全量结果：`bash scripts/check.sh` 通过，131 个测试、0 个失败。
- 安装诊断：`bash install.sh --doctor --target codex --offline` 通过，Suite `0.9.2` complete。

## 假设与说明

- 本次只使用 Skill/协议和现有 Batch helper，不新增宿主插件、后台守护进程或依赖。
- 官方 `quick_validate.py` 已实际运行，但当前 Python 3.14.4 环境缺少 `PyYAML`，报 `ModuleNotFoundError: No module named 'yaml'`；按任务约束未安装依赖。
- 独立前向场景由父任务在全新 evaluator 中执行；本 PDLC worker 不自行宣称该评估通过。

## 独立验收 finding closure

| Finding 指纹 | Closure 证据 |
|---|---|
| `batch-state/future-pending-worker + accepts-active-worker-before-current-completion + lifecycle-fields-not-phase-bound` | `test_应该_当前一批仍运行时_拒绝未来pending批次提前登记worker` 和 `test_应该_当批次仍pending或dispatching时_拒绝任何worker生命周期` 验证阶段屏障；v1/v2 的活动与未启动迁移测试验证兼容性。 |

## 上线前待办

- 由父任务使用一个 evaluator 在隔离临时工作区完成相关有限场景，并确认 evaluator 宿主终态及本轮 active worker 数为 0。
- Codex UI 中没有稳定 ref、且当前 list/query API 不可见的 11 个历史孤儿无法由 Skill 清理；需要用户通过 UI 或宿主支持渠道处理。
