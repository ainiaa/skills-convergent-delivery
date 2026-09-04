# Runtime Adapters

Runtime Adapter 只把 Batch Protocol 映射到当前宿主已有的任务能力，不实现第二套调度器。

Skill 规则本身不能创建、计时、中断或恢复宿主任务。下列动作只有在宿主本次会话实际提供对应 API 时才可执行；否则必须走手工交接，不能把协议目标写成已发生的宿主行为。

## 共同契约

worker 的登记、归属、宿主终态、watchdog、一次恢复和退出清场统一遵循 [执行控制](../../../references/execution-control.md)，本文件只说明 Batch 到宿主 API 的映射。

开始前把宿主本会话实际暴露的布尔能力从 stdin 交给：

```bash
python3 "$CONVERGE_BATCH_SKILL_DIR/../../scripts/runtime_adapter.py" negotiate --profile codex
```

automatic lifecycle 需要同会话稳定 `dispatch + query + tree_query`，以及具体 bridge 绑定的 `host_observed` capability observation 与每次原始 tree-query cleanup observation。`negotiate --profile codex|claude-code` 只产生 controller-attested Binding，不能自动派发或清场。没有 bridge 时所有路径都必须手工交接。Runtime Adapter 返回可执行的 Runtime Action，不代理宿主调用；terminal-only 只能查询/等待，不能作为完成或清场证据。每个操作都先由父控制器校验当前 `run_id + worker_ref`，不得用全局列表猜测。

## Bridge release gate

`bind_observed()` 仍是外部宿主 bridge 的内部入口，不是把 JSON 从普通 stdin 传入就能取得的来源声明。Codex Desktop 不把它作为默认路径；若将来接入 bridge，必须完成真实 dispatch → query 同一 `worker_ref` 至终态 → tree query 的端到端验证，才能使用 `host_observed`。

1. 先将 Batch 状态写为 `dispatching` 并固定 `dispatch_id`。
2. 创建调用携带当前 capsule并显式要求执行者使用 `$converge`；按 Batch state 原子保存 worker lifecycle 和 `recovery_count=0` 后进入 `running`。
3. 只接受匹配 `batch_id/dispatch_id` 的结构化 receipt；receipt 与 worker 宿主终态必须分别验证。
4. 连接异常、恢复或清场按执行控制处理；每次实际恢复前先把本 Batch 的 `recovery_count=1` 持久化。

## Codex

- 当前 Codex Desktop 的直接 `spawn_agent`、`list_agents`、`wait_agent`、`interrupt_agent` 调用只能形成 controller-attested 观察；没有 bridge 时一律手工交接，不能登记 Batch 或 `workers[]` lifecycle。
- **原生同会话子代理自动 lifecycle**只有 bridge 已提供同会话 `host_observed` `tree_query` Binding 后才先做一次只读 smoke：`spawn_agent` 返回精确 `worker_ref`，父控制器在运行时以 `list_agents(path_prefix=worker_ref)` 观察路径；`wait_agent` 只是 wake-up signal，醒来后必须以同一路径和带该 ref 的终态消息复查。Codex 不接受 `restrict_dispatch`。审查仍由 `external_runner` 的冻结 Review v3 request 完成。任何派发不确定、无 ref、非终态或 timeout 都不得重派，改为手工 capsule。
- 该 smoke 只证明当前会话。`create_thread` worktree 返回的 `clientThreadId` 不能作为 `worker_ref`；当前宿主没有可验证的 client-id 解析、跨会话精确 lifecycle query/interrupt 与 subtree observation 时，`checkpoint=cross_session` 必须维持手工 capsule，不得把 `external_runner` 或 queued message 伪称为 bridge。
- 用有界的 wait 跟进；超时只表示继续查询，不表示重新派发、无进展或可中断。
- 当前 Codex 若只能等待最终状态，`activity_query` 和 `process_query` 必须协商为 false，因此 Binding 为 `terminal-only`；重复 timeout 不能触发 `interrupt=true` 或消耗恢复预算。
- 排队消息只是消息，不是软探测；中断只用于用户 stop 或 `observed` Binding 已确认停滞后的收口。
- wait timeout 规范化为 `working`；宿主 `done/cancelled/failed` 分别规范化为 `completed/interrupted/blocked`。
- 恢复时按执行控制查询原任务，验证 receipt 后再推进状态。

## Claude Code

- 开始前确认当前会话实际暴露 `Agent` 与可查询的 task list；任一不可用时向 `negotiate --profile claude-code` 报 `dispatch=false` 或 `query=false`，按手工交接处理。不得根据 Claude Code 的安装或版本猜测能力。
- 当前会话可直接使用 `Agent` 创建前台或后台 subagent；以返回的 agent id 为 `worker_ref`，通过 task list 查询运行/完成状态。前台任务等待结果，后台任务只在宿主通知完成或 task list 显示终态后推进。
- 普通 subagent 限当前会话：恢复当前 run 时先查询同一 ref；若当前宿主已不能查询，转手工交接，不重新派发。Agent Teams 是实验能力，不作为默认 Batch 依赖。

## 其他宿主

`single-context` profile 始终为 manual。没有“创建新上下文 + 稳定引用 + 重新查询”三项能力时，输出 capsule 和期望 receipt，进入手工交接；不宣称已自动启动、查询、中断或恢复执行者。

宿主能力不足时按执行控制进行手工交接，不伪造已执行动作。
