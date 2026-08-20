# Runtime Adapters

Runtime Adapter 只把 Batch Protocol 映射到当前宿主已有的任务能力，不实现第二套调度器。

Skill 规则本身不能创建、计时、中断或恢复宿主任务。下列动作只有在宿主本次会话实际提供对应 API 时才可执行；否则必须走手工交接，不能把协议目标写成已发生的宿主行为。

## 共同契约

1. 先将 Batch 状态写为 `dispatching` 并固定 `dispatch_id`。
2. 创建新上下文成功后立即保存宿主返回的稳定 `worker_ref` 和 `recovery_count=0`，再进入 `running`。
3. 消息必须是当前 capsule，并显式要求执行者使用 `$converge`。
4. 连接中断或超时时，先查询原任务的 `worker_ref`；自动恢复前原子写入 `recovery_count=1`，结果不确定或计数已用尽就 blocked，不重复派发。
5. 只接受匹配 `batch_id` 和 `dispatch_id` 的结构化 receipt；自然语言“已完成”不放行。

## Codex

- 仅在当前 Codex 宿主实际暴露新任务/thread、等待、查询和中断工具时使用它们，将返回的 task/thread id 记为 `worker_ref`。
- 用有界的 wait 跟进；超时只表示继续查询，不表示重新派发。
- 恢复时根据 `worker_ref` 查询原任务，验证 receipt 后再推进状态。

## Claude Code

- 仅在当前环境可创建独立 Task/subagent，且可获得稳定、可重新查询的 `worker_ref` 时自动派发。
- 若只能发起不可恢复的子任务，不把它当作可靠调度；改为手工交接。

## 其他宿主

没有“创建新上下文 + 稳定引用 + 重新查询”三项能力时，输出 capsule 和期望 receipt，进入手工交接；不宣称已自动启动执行者。
