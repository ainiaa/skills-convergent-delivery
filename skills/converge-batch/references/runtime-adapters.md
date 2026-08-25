# Runtime Adapters

Runtime Adapter 只把 Batch Protocol 映射到当前宿主已有的任务能力，不实现第二套调度器。

Skill 规则本身不能创建、计时、中断或恢复宿主任务。下列动作只有在宿主本次会话实际提供对应 API 时才可执行；否则必须走手工交接，不能把协议目标写成已发生的宿主行为。

## 共同契约

worker 的登记、归属、宿主终态、watchdog、一次恢复和退出清场统一遵循 [执行控制](../../../references/execution-control.md)，本文件只说明 Batch 到宿主 API 的映射。

开始前把宿主本会话实际暴露的布尔能力从 stdin 交给：

```bash
python3 scripts/runtime_adapter.py negotiate --profile codex
```

automatic 至少要求稳定 `dispatch + query`。当前 Codex Desktop 的原生 create/query/wait/interrupt 工具是可信本地宿主：`negotiate --profile codex` 产生的 automatic `controller_attested` Binding 可自动派发和清场，不需要额外 receipt 协议。控制器必须保存工具返回的 `worker_ref`，只查询该 ref，派发不确定时不重派，并在下一 Batch 前再次查询。其他宿主仍只有在具体桥接冻结为 `host_observed` 时才能自动派发。Runtime Adapter 返回可执行的 Runtime Action，不代理宿主调用：父控制器必须执行 `watchdog_action` 返回且绑定精确 `task_id + worker_ref` 的 `query|wait|interrupt|block`。`terminal-only` 禁止自动探测、中断和恢复；没有 wait capability 时 action 退回 query。持有状态和 registry 的父控制器直接调用当前会话真实暴露的宿主工具；terminal worker 可 query 核实，但必须拒绝 wait/interrupt。每个操作都先由父控制器校验当前 `run_id + worker_ref`，不得用全局列表猜测。

## Bridge release gate

`bind_observed()` 仍是外部宿主 bridge 的内部入口，不是把 JSON 从普通 stdin 传入就能取得的来源声明。Codex Desktop 不把它作为默认路径：控制器直接使用宿主工具并记录返回的 ref 与终态。若将来接入其他宿主，必须完成真实 dispatch → query 同一 `worker_ref` 至终态 → tree query 的端到端验证，才能使用 `host_observed`。

1. 先将 Batch 状态写为 `dispatching` 并固定 `dispatch_id`。
2. 创建调用携带当前 capsule并显式要求执行者使用 `$converge`；按 Batch state 原子保存 worker lifecycle 和 `recovery_count=0` 后进入 `running`。
3. 只接受匹配 `batch_id/dispatch_id` 的结构化 receipt；receipt 与 worker 宿主终态必须分别验证。
4. 连接异常、恢复或清场按执行控制处理；每次实际恢复前先把本 Batch 的 `recovery_count=1` 持久化。

## Codex

- 当前 Codex Desktop 直接使用会话原生的 `spawn_agent`、`list_agents`、`wait_agent`、`interrupt_agent`，将返回的 task/thread id 记为 `worker_ref`；没有稳定 ref 或查询能力时才手工交接。
- 用有界的 wait 跟进；超时只表示继续查询，不表示重新派发、无进展或可中断。
- 当前 Codex 若只能等待最终状态，`activity_query` 和 `process_query` 必须协商为 false，因此 Binding 为 `terminal-only`；重复 timeout 不能触发 `interrupt=true` 或消耗恢复预算。
- `send_input(interrupt=false)` 只是排队，不能当作软探测；`interrupt=true` 仅用于用户 stop 或 `observed` Binding 已确认停滞后的收口。
- wait timeout 规范化为 `working`；宿主 `done/cancelled/failed` 分别规范化为 `completed/interrupted/blocked`。
- 恢复时按执行控制查询原任务，验证 receipt 后再推进状态。

## Claude Code

- 仅在当前环境可创建独立 Task/subagent、可获得稳定且可重新查询的 `worker_ref`，并由具体桥接产生 `host_observed` Binding 时自动派发。
- 若只能发起不可恢复的子任务或无法稳定 query，不把它当作可靠调度；协商结果为 manual 并改为手工交接。

## 其他宿主

`single-context` profile 始终为 manual。没有“创建新上下文 + 稳定引用 + 重新查询”三项能力时，输出 capsule 和期望 receipt，进入手工交接；不宣称已自动启动、查询、中断或恢复执行者。

宿主能力不足时按执行控制进行手工交接，不伪造已执行动作。
