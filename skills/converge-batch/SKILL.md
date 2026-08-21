---
name: converge-batch
description: Coordinate an existing finite multi-Batch software plan across fresh execution contexts. Use when asked to run a plan Batch by Batch, hand work between tasks, or supervise long-running sequential delivery; do not use for one implementation or ordinary review.
---

# Converge Batch：长计划调度器

只负责读取计划、预检 Batch、生成最小上下文胶囊、派发/恢复执行者并校验结构化 receipt。不读取业务代码，不做代码评审，不修改技术方案，不执行实现，也不持有代码 writer lease；计划级 scheduler lease 只防重复调度。

本 Skill 只接收 Plan Contract v3 的 `checkpoint=cross_session`。`checkpoint=same_session` 由根 `converge` 在同一会话顺序执行，不要求 commit，也不进入 Batch 状态机。

每个执行 Batch 必须在新上下文中显式调用 `$converge`。调度器只根据状态和 receipt 判断完成或阻塞，不能根据执行者的自然语言自评放行。

先将当前已选中 `converge-batch/SKILL.md` 所在目录的绝对路径记为 `CONVERGE_BATCH_SKILL_DIR`；helper 必须从这里解析，不能假设被调度项目本身包含该脚本。

## 1. 全量预检

开始前读取 [Batch Protocol v1](references/batch-contract.md) 和 [Runtime Adapters](references/runtime-adapters.md)，一次性检查：

- 计划有限且 Batch 顺序明确；
- 每批有目标、范围、消费/产出接口、基线、验收和真实验证方式；
- Batch 完成后仓库可继续构建或加载，不留下必须由下一批修复的半成品；
- 公共契约/数据库变更具有兼容顺序；
- 存在计划级 `final_acceptance`；
- 使用一个专用分支和 worktree，且没有不属于计划的脏改动；
- `converge` 已安装；宿主是否能创建/监控全新任务已记录。
- 用户已为这个跨会话 checkpoint 一次性授权各 Batch 产生本地 commit；未授权时在任何派发前阻塞或改用同会话顺序执行，不能把 Batch 权限解释为 commit 权限。

缺口一次性报告并阻塞。不得运行到后续 Batch 才逐项询问，也不得自行补技术方案。

## 2. 冻结计划并初始化

冻结 `plan_id`、revision、fingerprint、Batch 顺序和全局约束。使用 `python3 "$CONVERGE_BATCH_SKILL_DIR/scripts/batch_state.py" write --input -` 原子写入 Batch state Schema v3；旧 v1/v2 先做只添加身份/worker 生命周期字段的迁移。helper 同时以 `repo_id + plan_id` 获取默认两小时的 scheduler lease，第二个活动 run/window 必须阻塞；过期 owner 仅在确认已停止后用 `--takeover` 接管。后续所有更新必须校验 owner 和 revision。

计划内容变化时暂停并要求重新协调，不把新要求静默塞入当前 Batch。Batch state 与 `converge` 的单任务 state 分离。

## 3. 生成 context capsule

只从已冻结计划复制当前 Batch 必需信息：`planned_task=true`、正确的 `plan_id/task_id`、Provider Binding、全局约束、目标、范围、消费/产出接口、基线、验收和验证方式。不得附带整份会话或无关 Batch 内容。

按 Runtime Adapters 选择宿主能力，并遵循 [执行控制](../../references/execution-control.md) 的公共 worker/watchdog 规则。capsule 显式要求使用 `$converge`，并携带 `planned_task=true` 防止递归规划；宿主不支持时输出可直接交接的 capsule，并标记需要用户启动，不伪造自动调度。

上游 `converge-plan` 的 wave 用于确认依赖和路径冲突。**Batch Protocol v1 默认顺序**执行；当前 Schema 只有一个 `current_batch`，在多 worktree 集成和多 receipt 恢复协议落地前不得宣称并行写入。

## 4. 幂等派发和监控

- 每次继续前将完整 Batch state 通过 stdin 传给 `python3 "$CONVERGE_BATCH_SKILL_DIR/scripts/batch_next.py" --input -`，只执行其返回的一个动作。
- 派发前生成唯一 `dispatch_id`，状态依次为 `pending → dispatching → running → validating-receipt → completed`。
- 无法确认 dispatch 是否成功时进入 blocked，不重派相同 Batch。
- 只允许对查询/连接错误恢复一次；先将同一 Batch 的 `worker_ref` 和 `recovery_count=1` 持久化。测试、实现、环境或业务失败不得自动重跑整个 Batch。
- 只有当前 Batch completed 后才能派发下一批；顺序计划不并发执行代码。
- 自然语言回执不能替代宿主终态。receipt 通过但 worker 仍 Working 时继续查询/有界等待；只有 `worker_status=completed` 才能完成当前 Batch。
- 子任务进度由 `$converge` 的 Progress Receipt 提供；调度器只转述最新里程碑，长运行期间保证约 60 秒内有一次可见状态，不编造百分比或 ETA。

## 5. Receipt 与最终验收

receipt 必须匹配 `batch_id` 和 `dispatch_id`，绑定 `commit_id`、`tree_hash`、`verified_tree_hash`、新鲜验收证据和 open issues。验证源码树与最终提交不一致时拒绝完成。

所有 Batch 完成后核对累计验收矩阵并运行计划规定的 `final_acceptance`。失败时阻塞并要求形成明确修复 Batch；调度器不直接修代码。只有所有 worker 宿主终态、所有 Batch receipt 通过且最终验收新鲜通过时计划才能 complete。

## 6. 暂停、恢复和停止

- `pause`：当前执行者可结束，但不再派发新 Batch。
- `resume`：先校验计划 fingerprint、worktree、当前状态、dispatch 和 receipt，再继续。
- `stop`：停止后续派发，保留已有提交和状态；worker 处理按执行控制，不 reset、删除或操作其他任务。

所有退出路径应用执行控制的清场屏障。

发布、push、合并和其他外部动作不属于调度授权，始终需要用户明确确认。
