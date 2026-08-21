# 轻量状态 Schema v7

仅用于跨服务、跨会话、使用子代理或用户要求恢复的单个 `converge` 任务。无委托且可在当前上下文一次完成的简单任务可以不持久化。状态不得保存密钥、Cookie、请求正文或敏感业务数据；多 Batch 计划继续使用独立 Batch state。

## 1. 顶层结构

```json
{
  "schema_version": 7,
  "run_id": "run-<id>",
  "repo_id": "/absolute/git/common-dir",
  "task_key": "task-<scope-hash>",
  "writer_id": "writer-<id>",
  "revision": 0,
  "workspace": "/absolute/worktree",
  "baseline": {"commit": "<commit>", "diff_fingerprint": "<hash>"},
  "scope_fingerprint": "<hash>",
  "controller": {
    "package_version": "0.12.1",
    "protocol_version": 3,
    "protocol_fingerprint": "<sha256>",
    "snapshot": {"root": "/absolute/control-root/<hash>", "control_root": "/absolute/control-root", "source_root": "/absolute/original-suite", "package_version": "0.12.1", "protocol_version": 3, "protocol_fingerprint": "<sha256>", "files": []}
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
  "current_stage": "scope",
  "requires_stability_round": false,
  "status": "active | complete | blocked",
  "workers": [],
  "ledger": {},
  "handoff": {"goal": "<goal>", "last_verification": "<evidence>", "open_issues": [], "next_action": "<action>"}
}
```

`package_version` 只说明安装包版本。Snapshot closure 包含 `SKILL.md`、激活/状态/报告/TDD/压力场景 references、运行 helper 与创建时 registry 扫描发现的全部 Provider manifest。descriptor 冻结 `source_root/control_root`；验证要求 `root.parent=control_root`、目录名等于内容 fingerprint、所有中间目录和文件只读且 root 不在 source/目标 workspace 内。后续 helper 必须由 live `controller_snapshot.py run` 先验证再执行，不能直接启动 snapshot Python 文件。无 snapshot 的旧 v7 状态继续使用活动协议校验，不能伪造迁移。

`handoff.open_issues` 的新写入格式是字符串数组，一项对应一个尚待处理问题。旧 v5/v6/v7 字符串在读取时迁移：`none`、`0`、`No remaining scoped findings` 等明确无问题文本转为空数组，其他文本转为单元素数组；不再猜测自由文本中包含几项。

旧 v5/v6 状态第一次读取时只允许迁移为 v7：旧 `engine` 转成等价 Provider Binding，旧 worker 增加 `progress=null`，controller 转为分离版本。已有 controller 的 v6 只接受已发布且明确兼容的 0.10.0 协议身份，不能用当前身份覆盖未知或被篡改的来源。迁移不得推进阶段、修改 baseline/scope/ledger 或替换 Provider；新状态不得再写 `engine`。

## 2. Provider Binding

- workflow provider 只能是 `pdlc-v1` 或 `native-v1`。
- native workflow 可绑定一个 `tdd` stage provider；PDLC workflow 不得再混入其他 TDD provider。
- 每个引用冻结 manifest 绝对路径/fingerprint、版本、角色、task kind、canonical task contract/fingerprint，以及有序 `sources`。
- `sources` 中每项记录 `entrypoint|closure`、manifest 声明的 relative path、真实绝对路径与内容 fingerprint；声明入口必须从 source root 精确解析。stage provider 必须保留唯一真实入口；`entrypoint_candidates/source_fingerprint` 同时匹配。manifest、task contract、实际入口或 closure 任一变化都阻塞。
- `binding_fingerprint` 是完整 binding 的 canonical JSON sha256，恢复时任一来源变化都会阻塞。
- 兼容旧输出的 `engine` 可以由 binding 派生展示，但不能再写入正式状态。

## 3. Worker 与 Progress Receipt v1

```json
{
  "ref": "<stable host reference>",
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
- 子代理只回传 objective milestone；持有 writer lease 的父代理使用 `delivery_progress.py event --event milestone` 生成带可信时间的候选。
- heartbeat 只能由父代理根据 Runtime Adapter 对精确 worker ref 的宿主 query 结果，用 `delivery_progress.py observe` 生成。每次事件 `sequence + 1`；首次 heartbeat 允许 `objective_revision=0`，只有 milestone 才能让它 `+1`。
- 正式状态只保留每个 worker 最新快照，不保存无界事件日志。
- 文本去换行并限制长度；不得记录敏感输入。进度只用于用户可见性，不能替代宿主终态、测试、源码指纹或验收证据。
- complete 前当前 run 的全部 worker 必须到达宿主终态。

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

`ledger` 继续保存：

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
