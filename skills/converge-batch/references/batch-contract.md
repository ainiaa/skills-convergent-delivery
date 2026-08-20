# Batch Protocol v1

## Plan preflight

计划必须包含有限有序 Batch、全局约束和 `final_acceptance`。每个 Batch 必须能形成下列 context capsule：

```json
{
  "batch_id": "B1",
  "goal": "one verifiable outcome",
  "scope": ["allowed module/contract"],
  "global_constraints": ["copied from plan"],
  "consumes": ["earlier interface/commit"],
  "produces": ["interface/artifact for later batches"],
  "baseline": "commit",
  "acceptance": ["criterion"],
  "verification": ["real command or objective check"]
}
```

调度器只能复制和裁剪计划，不能通过读取业务代码自行填充缺失字段。

## State

Batch state 使用独立 Schema v1：`plan`、`preflight`、`batches`、`current_batch`、`final_acceptance`、owner 和 revision。计划 fingerprint、Batch 顺序和 capsule 在初始化后不可变。

Batch transitions：`pending → dispatching → running → validating-receipt → completed|blocked`。

Plan transitions：`active ↔ paused`，以及 `active|paused → blocked|stopped`、`active → complete`。

`pause`、`resume` 和 `stop` 只控制后续派发，不删除提交；paused 状态不能新建 dispatch，已有执行者仍可提交 receipt。任一 Batch blocked 时计划也必须 blocked。状态写入使用 revision CAS；stale update 必须失败。

## Dispatch

`dispatch_id` 在进入 dispatching 前生成，一旦设置不可改变，也不能出现在另一个 Batch。只有 active 计划的 `current_batch` 可以从 pending 进入 dispatching；后续 Batch 必须保持 pending。进入 running 必须记录可恢复的 `worker_ref`。处于不确定 dispatch 状态时 blocked，不自动重派。

## Receipt

```json
{
  "protocol_version": 1,
  "batch_id": "B1",
  "dispatch_id": "dispatch-B1",
  "commit_id": "commit",
  "tree_hash": "verified source tree",
  "verified_tree_hash": "same source tree",
  "acceptance": [
    {"criterion": "criterion", "evidence": "command/output", "result": "pass", "freshness": "fresh"}
  ],
  "open_issues": []
}
```

completed receipt 必须覆盖 capsule 全部 acceptance，全部为 fresh pass，且没有 open issues。helper 还必须在计划 worktree 中解析 `commit_id`，确认它的真实 Git tree 同时等于 `tree_hash` 和 `verified_tree_hash`；首次接收 receipt 时该提交必须是当前 clean workspace 的 HEAD。

## Final acceptance

计划 complete 前，所有 Batch 必须 completed，`current_batch` 为空，并且 `final_acceptance` 的每一项都有新鲜通过证据。单批通过不能替代整体集成验收。
