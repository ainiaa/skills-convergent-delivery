# Runtime Adapters

Runtime Adapter 只把 Batch Protocol 映射到当前宿主已有的任务能力，不实现第二套调度器。

Skill 规则本身不能创建、计时、中断或恢复宿主任务。下列动作只有在宿主本次会话实际提供对应 API 时才可执行；否则必须走手工交接，不能把协议目标写成已发生的宿主行为。

## 共同契约

1. 先将 Batch 状态写为 `dispatching` 并固定 `dispatch_id`。
2. 创建调用携带当前 capsule，并显式要求执行者使用 `$converge`；宿主返回后第一动作是保存稳定 `worker_ref`、`worker_role=batch-executor`、`worker_owner_run_id=<current run_id>`、`worker_status=working` 和 `recovery_count=0`，再 wait/query 或进入 `running`；不得 detached/fire-and-forget。
3. 创建调用不确定或没有返回稳定 ref 时进入 blocked/manual handoff，不进行其他派发。
4. 连接中断或超时时，先查询原任务的 `worker_ref`；自动恢复前原子写入 `recovery_count=1`，结果不确定或计数已用尽就 blocked，不重复派发。
5. 只接受匹配 `batch_id` 和 `dispatch_id` 的结构化 receipt；自然语言回执或“已完成”不放行。
6. receipt 到达后仍查询同一 `worker_ref`。宿主仍显示 Working 时继续有界 wait/query；只有宿主 `completed` 且 receipt 通过才能完成 Batch。无活动时按 watchdog 中断，随后确认 `interrupted`；无法查询或中断则计划 blocked 并报告 manual cleanup。
7. 正常、异常、停止、`no_progress` 和验证失败均执行等价 `finally` 清场，只处理 `worker_owner_run_id` 等于当前 run 的登记项；不得中断其他任务或历史 worker。

## Codex

- 仅在当前 Codex 宿主实际暴露新任务/thread、等待、查询和中断工具时使用它们，将返回的 task/thread id 记为 `worker_ref`。
- 用有界的 wait 跟进；超时只表示继续查询，不表示重新派发。
- 恢复时根据 `worker_ref` 查询原任务，验证 receipt 后再推进状态。
- 只对本轮登记的精确 task/thread id 调用查询或中断；全局列表中的其他 Working 项不属于当前调度器。

## Claude Code

- 仅在当前环境可创建独立 Task/subagent，且可获得稳定、可重新查询的 `worker_ref` 时自动派发。
- 若只能发起不可恢复的子任务，不把它当作可靠调度；改为手工交接。

## 其他宿主

没有“创建新上下文 + 稳定引用 + 重新查询”三项能力时，输出 capsule 和期望 receipt，进入手工交接；不宣称已自动启动执行者。

Runtime Adapter 只能使用宿主实际提供的 list/query/wait/interrupt。没有稳定 ref 或当前 API 不可见的历史孤儿无法由 Skill 清理，应报告能力边界并建议用户在 UI 或支持渠道处理。
