# Batch Protocol v1

## Plan preflight

Batch 仅用于 Plan Contract v6 的 `checkpoint=cross_session`，因此初始化前必须取得本地 commit 授权。`checkpoint=same_session` 的多任务由根控制器在同一会话顺序执行，不要求 commit，也不得仅因任务数量进入本协议。

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
  "provider_binding": {"selection": "auto", "reason": "frozen", "task_kind": "fix", "binding": {"controller": "converge", "workflow_provider": {"id": "native-v1", "manifest": "/absolute/path", "sources": []}, "stage_providers": {}}, "binding_fingerprint": "<sha256>"}
}
```

调度器只能复制和裁剪计划，不能通过读取业务代码自行填充缺失字段。
Schema v2+ capsule 的 `planned_task` 必须严格为 `true`，`plan_id` 必须匹配冻结计划，`task_id` 必须匹配 Batch 记录；任一缺失或错配都拒绝初始化，避免执行者递归规划。

Schema v4 capsule 必须携带完整 Provider Binding，包括 manifest、task contract、入口和 closure 来源摘要；只保存 Provider ID 不足以恢复，缺失或伪造时不得初始化。`preflight.commit_authorized` 必须严格为 `true`。该值只能来自用户对本计划的一次性本地 commit 授权；push、merge、tag、publish 仍不在授权内。

## State

Batch Protocol 保持 v1，持久化 state Schema 只接受 v4，完成回执使用 Receipt v4：`plan`、`preflight`、`batches`、`current_batch`、`final_acceptance`、`delegate_state_root`、owner 和 revision。每个 Batch 必须持久化 `task_id`、完整 Provider Binding、`worker_ref`、`worker_role`、`worker_owner_run_id`、`worker_status` 和 `recovery_count`；恢复次数只能从 0 增至 1。旧 Schema v1-v3 直接拒绝。

状态文件和 scheduler lease 都以 `repo_id + plan_id` 唯一定位；run takeover 只在同一状态文件转移 owner，不创建第二份状态。lease 默认两小时并在每次成功写入时续期；同一计划的活动 owner 会阻塞第二个 run/window。协调者崩溃且 lease 到期后，只有明确传入 `--takeover` 才能由新 owner 接管。

Batch transitions：`pending → dispatching → running → validating-receipt → completed|blocked`。

Plan transitions：`active ↔ paused`，以及 `active|paused → blocked|stopped`、`active → complete`。

`pause`、`resume` 和 `stop` 只控制后续派发，不删除提交；paused 状态不能新建 dispatch，已有执行者仍可提交 receipt。任一 Batch blocked 时计划也必须 blocked。状态写入使用 revision CAS；stale update 必须失败。

## Dispatch

`dispatch_id` 在进入 dispatching 前生成，一旦设置不可改变，也不能出现在另一个 Batch。只有 active 计划的 `current_batch` 可以从 pending 进入 dispatching；后续 Batch 必须保持 pending。进入 running 必须在同一 revision 记录可恢复的 `worker_ref`、固定 `worker_role=controller-delegate`、独立且不可变的 `delegate_run_id`、匹配 scheduler state `run_id` 的 `worker_owner_run_id` 和 `worker_status=working`；每次实际恢复前把 `recovery_count` 单调写回，超过一次即阻塞。处于不确定 dispatch 状态时 blocked，不自动重派。

## Receipt

```json
{
  "protocol_version": 4,
  "batch_id": "B1",
  "dispatch_id": "dispatch-B1",
  "commit_id": "commit",
  "tree_hash": "verified source tree",
  "verified_tree_hash": "same source tree",
  "parent_commit_id": "previous receipt commit or plan baseline",
  "delegate_run_id": "delegate-B1",
  "delegate_state_revision": 4,
  "delegate_source_fingerprint": "<sha256>",
  "delegate_source_receipt": {"schema_version": 2, "source_fingerprint": "<same sha256>", "changed_entries": []},
  "acceptance": [
    {"criterion": "criterion", "evidence": "command/output", "result": "pass", "freshness": "fresh"}
  ],
  "open_issues": []
}
```

Receipt v4 不接受调用者内嵌的 `delegate_state` 或自算 hash。helper 从 `delegate_state_root + repo_id + task_id + delegate_run_id` 派生正式 Single State 路径并读取真源，并要求回执中的 Source Receipt v2 与正式状态完全一致。completed receipt 必须覆盖 capsule 全部 acceptance，全部为源码绑定的 fresh pass，且没有 open issues。`parent_commit_id` 必须等于前一 Batch commit（首批为计划 baseline），且 Git ancestry 必须成立。Batch 从 `validating-receipt` 进入 `completed` 还要求同一 `worker_ref` 的 `worker_status=completed`。

checkpoint 的真实 Git tree 必须等于 Source Receipt 的基线加逐文件改动，包含内容、删除、权限和符号链接；不能遗漏验证内容或夹带额外文件。允许先验证再提交相同内容。历史 delegate 仍完整校验身份、Trace 和 Evidence，但 coverage 配置从对应 checkpoint 读取，不要求旧源码等于后续批次的工作区。当前 `validating-receipt` 与计划最终 `complete` 仍要求工作区内容匹配对应 checkpoint。此检查不切换 checkout，也不产生第二套状态。

## Final acceptance

计划 complete 前，所有 Batch 必须 completed，所有本 run worker 都已进入宿主终态，`current_batch` 为空，并且 `final_acceptance` 的每一项都有新鲜通过证据。单批通过不能替代整体集成验收；上一 worker 未终结或 receipt 未通过时不得派发下一批。

## Cleanup barrier

公共 worker/watchdog/清场行为以 [执行控制](../../../references/execution-control.md) 为唯一真源。Batch 额外要求把无法完成的清场结果写为 blocked，并在 `blocked_reason` 保留需 manual cleanup 的精确 ref。

最终 `final_acceptance` 的 criterion 列表从初始化起固定，不能添加、删除、替换、重排或重复。只有 evidence/result/freshness/source_fingerprint 可以在未通过时补充，已经通过的最终验收仍不可改写。

计划 complete 时，每项 `final_acceptance[].evidence` 必须是 `evidence_contract.py run` 真实执行生成的 observed Evidence Receipt 对象，退出码为 0，回执来源和 fingerprint 有效，且 source 精确等于当前工作区相对最后 Batch baseline 的 Source Receipt；外层 source_fingerprint 也必须一致。文本、缺失、失败、篡改或旧源码回执均不能放行。最终源码仍必须对应最后 Batch 的已验证提交；各 Batch receipt 内的 evidence 摘要继续由正式 delegate state 和提交链复核，不能替代最终检查。
