# Batch Protocol v1

## Plan preflight

Batch 仅用于 Plan Contract v3 的 `checkpoint=cross_session`，因此初始化前必须取得本地 commit 授权。`checkpoint=same_session` 的多任务由根控制器在同一会话顺序执行，不要求 commit，也不得仅因任务数量进入本协议。

计划必须包含有限有序 Batch、全局约束和 `final_acceptance`。每个 Batch 必须能形成下列 context capsule：

```json
{
  "planned_task": true,
  "plan_id": "plan-example",
  "task_id": "T1",
  "batch_id": "B1",
  "goal": "one verifiable outcome",
  "scope": ["allowed module/contract"],
  "global_constraints": ["copied from plan"],
  "consumes": ["earlier interface/commit"],
  "produces": ["interface/artifact for later batches"],
  "baseline": "commit",
  "acceptance": ["criterion"],
  "verification": ["real command or objective check"],
  "provider_binding": {
    "controller": "converge",
    "workflow_provider": "native-v1",
    "stage_providers": {},
    "binding_fingerprint": "<sha256>"
  }
}
```

调度器只能复制和裁剪计划，不能通过读取业务代码自行填充缺失字段。
Schema v2+ capsule 的 `planned_task` 必须严格为 `true`，`plan_id` 必须匹配冻结计划，`task_id` 必须匹配 Batch 记录；任一缺失或错配都拒绝初始化，避免执行者递归规划。

Schema v3 capsule 还必须携带计划中冻结且摘要匹配的 Provider Binding；缺失或伪造时不得初始化。`preflight.commit_authorized` 必须严格为 `true`。该值只能来自用户对本计划的一次性本地 commit 授权；旧 v1/v2 迁移时必须显式补入授权和 Provider Binding，不能由 helper 推断。push、merge、tag、publish 仍不在授权内。

## State

Batch Protocol 保持 v1，持久化 state Schema 升级为 v3：`plan`、`preflight`、`batches`、`current_batch`、`final_acceptance`、owner 和 revision。每个新 Batch 持久化 `task_id`、Provider Binding、`worker_ref`、`worker_role`、`worker_owner_run_id`、`worker_status` 和 `recovery_count`；恢复次数只能从 0 增至 1。`worker_status` 活动态为 `working`，宿主终态只能是 `completed|interrupted|blocked`。reader 可读取旧 Schema v1/v2，但下一次写入必须先做一次只添加 capsule identity、Provider Binding、recovery 和 worker lifecycle 的原子迁移；迁移不得同时改变计划或 Batch 行为状态。旧状态已有 active worker 时，迁移前必须用保存的 ref 查询真实宿主状态，不能猜测终态。新状态不能再以 v1/v2 初始化。

helper 另以 `repo_id + plan_id` 建立默认两小时的 scheduler lease，并在每次成功写入时续期；同一计划的活动 owner 会阻塞第二个 run/window。协调者崩溃且 lease 到期后，只有明确传入 `--takeover` 才能由新 owner 接管，活动 lease 即使带 takeover 也不能抢占。该 lease 只保护计划派发权，不授予代码写权，也不替代每个 `$converge` worker 的 worktree/task writer lease。

Batch transitions：`pending → dispatching → running → validating-receipt → completed|blocked`。

Plan transitions：`active ↔ paused`，以及 `active|paused → blocked|stopped`、`active → complete`。

`pause`、`resume` 和 `stop` 只控制后续派发，不删除提交；paused 状态不能新建 dispatch，已有执行者仍可提交 receipt。任一 Batch blocked 时计划也必须 blocked。状态写入使用 revision CAS；stale update 必须失败。

## Dispatch

`dispatch_id` 在进入 dispatching 前生成，一旦设置不可改变，也不能出现在另一个 Batch。只有 active 计划的 `current_batch` 可以从 pending 进入 dispatching；后续 Batch 必须保持 pending。进入 running 必须在同一 revision 记录可恢复的 `worker_ref`、固定 `worker_role=controller-delegate`、独立且不可变的 `delegate_run_id`、匹配 scheduler state `run_id` 的 `worker_owner_run_id` 和 `worker_status=working`；每次实际恢复前把 `recovery_count` 单调写回，超过一次即阻塞。处于不确定 dispatch 状态时 blocked，不自动重派。

## Receipt

```json
{
  "protocol_version": 2,
  "batch_id": "B1",
  "dispatch_id": "dispatch-B1",
  "commit_id": "commit",
  "tree_hash": "verified source tree",
  "verified_tree_hash": "same source tree",
  "delegate_run_id": "delegate-B1",
  "delegate_state": {"status": "complete", "...": "完整 Converge state"},
  "delegate_state_fingerprint": "<canonical sha256>",
  "acceptance": [
    {"criterion": "criterion", "evidence": "command/output", "result": "pass", "freshness": "fresh"}
  ],
  "open_issues": []
}
```

completed receipt 必须覆盖 capsule 全部 acceptance，全部为 fresh pass，且没有 open issues。helper 还必须在计划 worktree 中解析 `commit_id`，确认它的真实 Git tree 同时等于 `tree_hash` 和 `verified_tree_hash`；首次接收 receipt 时该提交必须是当前 clean workspace 的 HEAD。回执必须绑定完整、摘要匹配的子 Converge state；其 `run_id/task_key/workspace` 必须分别匹配冻结的 delegate run、Batch task 和计划 worktree，并通过单任务状态机的 complete/清场校验。Batch 从 `validating-receipt` 进入 `completed` 还要求同一 `worker_ref` 的 `worker_status=completed`。

## Final acceptance

计划 complete 前，所有 Batch 必须 completed，所有本 run worker 都已进入宿主终态，`current_batch` 为空，并且 `final_acceptance` 的每一项都有新鲜通过证据。单批通过不能替代整体集成验收；上一 worker 未终结或 receipt 未通过时不得派发下一批。

## Cleanup barrier

公共 worker/watchdog/清场行为以 [执行控制](../../../references/execution-control.md) 为唯一真源。Batch 额外要求把无法完成的清场结果写为 blocked，并在 `blocked_reason` 保留需 manual cleanup 的精确 ref。
