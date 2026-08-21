# 轻量状态 Schema v9

仅用于跨服务、跨会话、使用子代理或用户要求恢复的单个 `converge` 任务。无委托且可在当前上下文一次完成的简单任务可以不持久化。状态不得保存密钥、Cookie、请求正文或敏感业务数据；多 Batch 计划继续使用独立 Batch state。

## 1. 顶层结构

```json
{
  "schema_version": 9,
  "run_id": "run-<id>",
  "repo_id": "/absolute/git/common-dir",
  "task_key": "task-<scope-hash>",
  "writer_id": "writer-<id>",
  "revision": 0,
  "workspace": "/absolute/worktree",
  "baseline": {"commit": "<commit>", "diff_fingerprint": "<hash>"},
  "scope_fingerprint": "<hash>",
  "source_fingerprint": "<current Source Receipt fingerprint>",
  "controller": {
    "package_version": "0.16.0",
    "protocol_version": 6,
    "protocol_fingerprint": "<sha256>",
    "snapshot": {"root": "/absolute/control-root/<hash>", "control_root": "/absolute/control-root", "source_root": "/absolute/original-suite", "package_version": "0.16.0", "protocol_version": 6, "protocol_fingerprint": "<sha256>", "files": []}
  },
  "provider_binding": {
    "selection": "auto | explicit",
    "reason": "<selection reason>",
    "task_kind": "feature | fix | refactor",
    "binding": {
      "controller": "converge",
      "workflow_provider": {"id": "native-v1", "version": "1", "role": "workflow", "manifest": "/absolute/manifest", "manifest_fingerprint": "<sha256>", "task_kind": "feature", "contract": {}, "contract_fingerprint": "<sha256>", "sources": []},
      "stage_providers": {}
    },
    "binding_fingerprint": "<sha256>"
  },
  "runtime_binding": null,
  "execution_control": {
    "routing": {"schema_version": 1, "status": "frozen", "assessment_count": 1, "route": "inline", "review_tier": "low", "profile_fingerprint": "<sha256>"},
    "review": {"protocol_version": 2, "source_fingerprint": "<same current source>", "repair_budget_remaining": 1, "re_review_budget_remaining": 1, "integration_budget_remaining": 0, "requests": []}
  },
  "current_stage": "scope",
  "requires_stability_round": false,
  "status": "active | complete | blocked",
  "workers": [],
  "worker_tree_receipt": null,
  "ledger": {},
  "handoff": {"goal": "<goal>", "last_verification": "<evidence>", "open_issues": [], "next_action": "<action>"}
}
```

`package_version` 只说明安装包版本。Snapshot closure 包含 `SKILL.md`、激活/状态/报告/TDD/压力场景 references、运行 helper 与创建时 registry 扫描发现的全部 Provider manifest。descriptor 冻结 `source_root/control_root`；验证要求 `root.parent=control_root`、目录名等于内容 fingerprint、所有中间目录和文件只读且 root 不在 source/目标 workspace 内。后续 helper 必须由 live `controller_snapshot.py run` 先验证再执行，不能直接启动 snapshot Python 文件。无 snapshot 的旧 v7 状态继续使用活动协议校验，不能伪造迁移。

`handoff.open_issues` 的新写入格式是字符串数组，一项对应一个尚待处理问题。旧 v5/v6/v7 字符串在读取时迁移：`none`、`0`、`No remaining scoped findings` 等明确无问题文本转为空数组，其他文本转为单元素数组；不再猜测自由文本中包含几项。

无 worker 的旧 v5-v8 状态可保守迁移为 v9：旧 `engine` 转成等价 Provider Binding，缺失的宿主事实明确记为 `legacy_unavailable`，不能据此完成任务。任何旧状态只要已有 worker 就必须人工恢复，不能补写或猜测其 task、宿主终态和清场事实。迁移不得推进阶段、修改 baseline/scope/ledger 或替换 Provider；新状态不得再写 `engine`。

## 2. Provider Binding

- workflow provider 只能是 `pdlc-v1` 或 `native-v1`。
- native workflow 可绑定一个 `tdd` stage provider；PDLC workflow 不得再混入其他 TDD provider。
- 每个引用冻结 manifest 绝对路径/fingerprint、版本、角色、task kind、canonical task contract/fingerprint，以及有序 `sources`。
- `sources` 中每项记录 `entrypoint|closure`、manifest 声明的 relative path、真实绝对路径与内容 fingerprint；声明入口必须从 source root 精确解析。stage provider 必须保留唯一真实入口；`entrypoint_candidates/source_fingerprint` 同时匹配。manifest、task contract、实际入口或 closure 任一变化都阻塞。
- `binding_fingerprint` 是完整 binding 的 canonical JSON sha256，恢复时任一来源变化都会阻塞。
- 兼容旧输出的 `engine` 可以由 binding 派生展示，但不能再写入正式状态。

## 3. Worker、Runtime Binding Schema v1 与 Progress Receipt v1

```json
{
  "ref": "<stable host reference>",
  "parent_ref": null,
  "task_id": "<Plan Contract task id or task key>",
  "depth": 1,
  "may_dispatch": false,
  "role": "implementation",
  "owner_run_id": "run-<id>",
  "status": "working | completed | interrupted | blocked",
  "progress": {
    "sequence": 2,
    "objective_revision": 1,
    "event": "heartbeat | milestone",
    "phase": "understanding | planning | reproducing | testing | implementing | verifying | reviewing | closing",
    "milestone": "<current result>",
    "activity": "<latest objective activity>",
    "evidence": "<bounded evidence summary>",
    "next_action": "<one next action>",
    "observed_at": "<parent-stamped UTC time>"
  }
}
```

- 宿主返回稳定 ref 后立即登记 worker，初始 `progress=null`。
- 只有根控制器可以派发；worker 是 `parent_ref=null/depth=1/may_dispatch=false` 的叶子。宿主任务树中出现未登记后代时阻止 complete。
- 子代理只回传 objective milestone；持有 writer lease 的父代理使用 `delivery_progress.py event --event milestone` 生成带可信时间的候选。
- heartbeat 只能由父代理根据 Runtime Adapter 对精确 worker ref 的宿主 query 结果，用 `delivery_progress.py observe` 生成。每次事件 `sequence + 1`；首次 heartbeat 允许 `objective_revision=0`，只有 milestone 才能让它 `+1`。
- 正式状态只保留每个 worker 最新快照，不保存无界事件日志。
- 文本去换行并限制长度；不得记录敏感输入。进度只用于用户可见性，不能替代宿主终态、测试、源码指纹或验收证据。
- complete 前当前 run 的全部 worker 必须到达宿主终态。

完成态若曾创建 worker，还必须携带同 revision 的清场回执：

```json
{
  "schema_version": 1,
  "observed_revision": 4,
  "observed_at": "2026-08-21T00:00:00Z",
  "runtime_fingerprint": "<sha256>",
  "mode": "tree_query | restrict_dispatch",
  "registered_refs": ["<worker-ref>"],
  "active_refs": [],
  "unexpected_refs": []
}
```

第一次登记 worker 时必须同时冻结 `runtime_adapter.py negotiate` 产生的 Runtime Binding；之后不可替换。清场回执只能由 `runtime_adapter.py receipt` 根据该 Binding 生成，`mode` 必须来自已冻结的 `tree_query` 或 `restrict_dispatch` 能力，且 `runtime_fingerprint` 必须匹配。`registered_refs` 必须与 registry 完全一致；`active_refs` 只能引用 registry 中 worker。complete 时两类未清场引用都必须为空；blocked 若存在 worker 或树回执，也必须使用同 revision 回执并精确列出所有仍 working 的引用。blocked 后仍允许用后续 revision 只更新既有 worker 的宿主生命周期和清场回执，不能登记新 worker、改写任务事实或恢复 active；因此中断成功可以被准确落盘。发现意外后代时保留在 `unexpected_refs` 并进入 blocked，供用户精确清理。

生成和展示：

```bash
python3 scripts/delivery_progress.py event --worker-ref <ref> --event milestone \
  --phase implementing --milestone "目标测试通过" --activity "完成最小实现" \
  --evidence "26 tests passed" --next-action "运行状态迁移测试" < state.json

python3 scripts/delivery_progress.py observe --worker-ref <ref> \
  --host-status working --evidence "host query: process active" < state.json

python3 scripts/delivery_progress.py status < state.json
```

父代理负责按不超过约 60 秒的可见节奏向用户转述最新快照；去重指纹同时包含 worker 宿主 lifecycle，working→completed/blocked/interrupted 不得被相同进度文本隐藏。长测试或工具仍在运行时不编造百分比或 ETA。

## 4. Ledger 与阶段

`ledger` 继续保存；所有 fresh/pass 验收必须携带与顶层 `source_fingerprint` 相同的源码指纹。`execution_control` 是路由和审查的唯一真源，保存 frozen route、1–2 次画像评估、Review Protocol v2 单轴请求以及剩余 repair/re-review/integration 预算：

- `completed_rounds`：0–2；
- append-only `repair_fingerprints` 与 `checks`；
- 当前 `acceptance` 及被替换事实的 `acceptance_history`；
- 增量回执所需的 `report_history`。

Native 和第三方 TDD 使用：`scope → round-1-build → round-1-semantic-review → verify-round-1（高风险）→ round-2-risk-review → verify-final`。PDLC workflow 只使用 `pdlc-run`，其细粒度阶段仍由 PDLC 自己保存。终态 complete 必须位于最终阶段并具有全部 fresh/pass 验收证据；blocked 必须提供 `blocked_code/reason`。

## 5. 路径、租约与原子写入

正式根目录固定为 `~/.convergent-delivery/state/`。路径只能由 `repo_id + task_key + run_id` 推导；候选 JSON 只通过 stdin 提交。每次写入必须：

1. 续期两小时 writer lease；
2. 提交完整下一 revision；
3. 在活动 owner 锁内校验 repo/task/run/writer、冻结字段、Provider 和状态转换；
4. 在正式目录创建 `0600` 临时文件，`fsync` 后原子替换。

```bash
python3 scripts/delivery_state.py path --repo <repo> --task-key <task> --run-id <run>
python3 scripts/delivery_state.py write --input - --repo-id <repo> --task-key <task> \
  --run-id <run> --writer-id <writer> --expected-revision <revision>
python3 scripts/delivery_next.py --state <derived-path> --run-id <run> \
  --writer-id <writer> --revision <revision>
```

不得把 `/tmp` 文件、调用者指定的任意路径或自然语言回执当作状态真源。workspace 只有在同 owner 的有效 lease move 后才能改变；revision、worker 身份和终态均不可回退。
