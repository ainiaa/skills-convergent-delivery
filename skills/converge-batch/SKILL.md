---
name: converge-batch
description: Coordinate an existing finite multi-Batch software plan across fresh execution contexts. Use when asked to run a plan Batch by Batch, hand work between tasks, or supervise long-running sequential delivery; do not use for one implementation or ordinary review.
---

# Converge Batch：长计划调度器

只负责读取计划、预检 Batch、生成最小上下文胶囊、派发/恢复执行者并校验结构化 receipt。不读取业务代码，不做代码评审，不修改技术方案，不执行实现，也不持有代码 writer lease。

每个执行 Batch 必须在新上下文中显式调用 `$converge`。调度器只根据状态和 receipt 判断完成或阻塞，不能根据执行者的自然语言自评放行。

先将当前已选中 `converge-batch/SKILL.md` 所在目录的绝对路径记为 `CONVERGE_BATCH_SKILL_DIR`；helper 必须从这里解析，不能假设被调度项目本身包含该脚本。

## 1. 全量预检

开始前读取 [Batch Protocol v1](references/batch-contract.md)，一次性检查：

- 计划有限且 Batch 顺序明确；
- 每批有目标、范围、消费/产出接口、基线、验收和真实验证方式；
- Batch 完成后仓库可继续构建或加载，不留下必须由下一批修复的半成品；
- 公共契约/数据库变更具有兼容顺序；
- 存在计划级 `final_acceptance`；
- 使用一个专用分支和 worktree，且没有不属于计划的脏改动；
- `converge` 已安装；宿主是否能创建/监控全新任务已记录。

缺口一次性报告并阻塞。不得运行到后续 Batch 才逐项询问，也不得自行补技术方案。

## 2. 冻结计划并初始化

冻结 `plan_id`、revision、fingerprint、Batch 顺序和全局约束。使用 `python3 "$CONVERGE_BATCH_SKILL_DIR/scripts/batch_state.py" write --input -` 原子写入 Batch Schema v1；后续所有更新必须校验 owner 和 revision。

计划内容变化时暂停并要求重新协调，不把新要求静默塞入当前 Batch。Batch state 与 `converge` 的单任务 state 分离。

## 3. 生成 context capsule

只从已冻结计划复制当前 Batch 必需信息：全局约束、目标、范围、消费/产出接口、基线、验收和验证方式。不得附带整份会话或无关 Batch 内容。

宿主支持任务/子代理时，创建全新上下文并发送 capsule，显式要求使用 `$converge`；宿主不支持时输出可直接交接的 capsule，并标记需要用户启动，不伪造自动调度。

## 4. 幂等派发和监控

- 派发前生成唯一 `dispatch_id`，状态依次为 `pending → dispatching → running → validating-receipt → completed`。
- 无法确认 dispatch 是否成功时进入 blocked，不重派相同 Batch。
- 只允许对查询/连接错误进行有限重试；测试、实现、环境或业务失败不得自动重跑整个 Batch。
- 只有当前 Batch completed 后才能派发下一批；顺序计划不并发执行代码。
- 进度只在 Batch 开始、完成、阻塞、用户查询或整体结束时汇报。

## 5. Receipt 与最终验收

receipt 必须匹配 `batch_id` 和 `dispatch_id`，绑定 `commit_id`、`tree_hash`、`verified_tree_hash`、新鲜验收证据和 open issues。验证源码树与最终提交不一致时拒绝完成。

所有 Batch 完成后核对累计验收矩阵并运行计划规定的 `final_acceptance`。失败时阻塞并要求形成明确修复 Batch；调度器不直接修代码。只有所有最终验收新鲜通过时计划才能 complete。

## 6. 暂停、恢复和停止

- `pause`：当前执行者可结束，但不再派发新 Batch。
- `resume`：先校验计划 fingerprint、worktree、当前状态、dispatch 和 receipt，再继续。
- `stop`：停止后续派发，保留已有提交和状态；不 reset、删除或强杀执行者。

发布、push、合并和其他外部动作不属于调度授权，始终需要用户明确确认。
