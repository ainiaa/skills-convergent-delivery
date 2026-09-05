# 轻量状态 Schema v10 / v11

仅用于跨服务、跨会话、使用子代理或用户要求恢复的单个 `converge` 任务。无委托且可在当前上下文一次完成的简单任务可以不持久化。状态不得保存密钥、Cookie、请求正文或敏感业务数据；多 Batch 计划继续使用独立 Batch state。

## 1. 顶层结构

```json
{
  "schema_version": 10,
  "run_id": "run-<id>",
  "repo_id": "/absolute/git/common-dir",
  "task_key": "task-<scope-hash>",
  "writer_id": "writer-<id>",
  "revision": 0,
  "workspace": "/absolute/worktree",
  "baseline": {"commit": "<commit>", "diff_fingerprint": "<hash>"},
  "scope_fingerprint": "<hash>",
  "source_fingerprint": "<current Source Receipt fingerprint>",
  "source_receipt": {"schema_version": 2, "baseline_commit": "<commit>", "changed_entries": [], "source_fingerprint": "<same fingerprint>"},
  "controller": {
    "package_version": "0.1.0",
    "protocol_version": 17,
    "protocol_fingerprint": "<sha256>",
    "extensions": ["multimodel"],
    "snapshot": {"root": "/absolute/control-root/<hash>", "control_root": "/absolute/control-root", "source_root": "/absolute/original-suite", "package_version": "0.1.0", "protocol_version": 17, "protocol_fingerprint": "<sha256>", "extensions": ["multimodel"], "files": []}
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
  "host_sync": {"mode": "native | text | legacy_unavailable", "acknowledged_fingerprint": null, "evidence_level": "controller_attested | host_observed", "fallback": "optional: {reason, evidence_ref, disclosure_ref}; text only"},
  "execution_control": {
    "routing": {"schema_version": 2, "status": "frozen", "assessment_count": 1, "route": "inline", "review_tier": "low", "profile": {"schema_version": 2, "assessment_phase": "frozen", "scope": "local", "coupling": "single", "uncertainty": "low", "verification": "local", "risk_flags": [], "cross_session": false, "delegable_tasks": 0, "context_isolation_benefit": false}, "allowed_paths": ["src"], "integration_required": false, "profile_fingerprint": "<sha256>"},
    "review": {"protocol_version": 3, "repair_budget_remaining": 1, "re_review_budget_remaining": 1, "integration_budget_remaining": 0, "rounds": [{"source_fingerprint": "<source>", "requests": []}]}
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

`package_version` 只说明安装包版本。Snapshot closure 默认只包含根控制器、状态/报告/TDD references、实际可路由的 plan/review/batch/eval Skill 与确定性 helper。`extensions` 是创建时冻结的有序集合：`multimodel` 增加 runner、角色与评测运行时；`autonomy` 增加有界续跑；仅开发/发布时显式选择的 `autonomy-eval` 才增加自治评测器与 fixtures。Hook 自治只冻结 `autonomy`，service 自治额外冻结 `multimodel`；旧 v16 `extended` descriptor 统一映射到三者，所有读取路径得到同一能力集合。descriptor 冻结 `source_root/control_root`；验证要求 `root.parent=control_root`、目录名等于内容 fingerprint、所有中间目录和文件只读且 root 不在 source/目标 workspace 内。后续 helper 必须由 live `controller_snapshot.py run` 启动：它先验证快照不可变性（含被启动 bootstrap 的内容），再由快照自身验证其冻结协议并执行，不能直接启动 snapshot Python 文件；因此升级不会把有效 active run 改按新协议解释。trusted runner 只额外授权冻结的 `skills/converge-batch/scripts/batch_next.py` 与 `batch_state.py`，不得执行任意 `skills/` 路径或测试脚本。旧快照只允许协议明示的精确清场兼容，不能伪造升级。

`handoff.open_issues` 的新写入格式是字符串数组，一项对应一个尚待处理问题。旧 v5/v6/v7 字符串在读取时迁移：`none`、`0`、`No remaining scoped findings` 等明确无问题文本转为空数组，其他文本转为单元素数组；不再猜测自由文本中包含几项。

无 worker 的旧 v5-v9 状态可保守迁移为 v10：旧 `engine` 转成等价 Provider Binding，Review v2 转成不可变历史轮次，缺失的宿主计划和 Source Receipt 明确记为不可用，不能据此伪造事实。任何旧状态只要已有 worker 就必须人工恢复，不能补写或猜测其 task、宿主终态和清场事实。迁移不得推进阶段、修改 baseline/scope/ledger 或替换 Provider；新状态不得再写 `engine`。

`source_receipt` 使用 Source Receipt v2，绑定当前 Git baseline、HEAD/tree、diff、路径类型、执行权限与内容摘要；存在时必须与 `source_fingerprint` 完全一致。Routing Receipt v3 由 `task_profile.freeze_routing` 唯一生成：它冻结原始请求摘要与 `full_closure_required`，完成时 helper 重算 route/review tier/integration requirement/profile fingerprint，逐项检查真实 changed paths 位于 `allowed_paths`，并阻止路径暴露出画像未声明的 SQL、迁移、权限、安全、公共 API 等风险。全量路由在同一 `execution_control` 内必须另有 `closure` gate：它冻结完整 Plan v6，要求 Plan requirement 与 routing 精确匹配、Plan baseline 的 commit/diff identity 与 state baseline 匹配、每个 Plan task 的 Provider Binding 与 state Binding 精确相同，所有 Plan task 与 closure matrix 均不得超出 frozen routing scope；gate 还保存 Plan audit envelope，complete 时 helper 在当前 workspace 重新运行 audit，要求每条 task source chain 的末端等于真实 workspace Source Receipt，结果覆盖 state acceptance、对当前 Source Receipt 完整通过。定向图谱回执必须携带当前 Source Receipt 的 observed `codegraph` Evidence Receipt，并以冻结 `allowed_paths`、matrix chains 与 scope fingerprint 确定性生成查询，再将 stdout fingerprint 绑定为图谱输出；它还绑定 Closure Review v3 request。只有 gate=`pass`、当前源码的独立 blind closure review 通过且所有验收证据新鲜时才可 complete。closure 最多两条历史记录，第二条只能在首次 finding 后通过；预算耗尽的 finding 必须 blocked/uncovered。旧 Routing v1/v2 只读兼容，不能写入新 complete。`delivery_state.py doctor` 对不可解析和非对象 managed JSON 都返回 `health=blocked`，不会静默跳过磁盘损坏。

Schema v11 仅用于用户明确启用自治交付的 run。在既有 `execution_control` 内增加不可变 `autonomy`：它冻结需求、范围和验收 manifest，并保存至多一次 initial audit 与一次修复后的 re-audit。每批 audit 必须注明当前源码指纹、覆盖的 manifest 项、finding 指纹和产生它的 Evidence Receipt 指纹；只有覆盖全部项、finding 为空、receipt 对当前源码成功且指纹等于当前源码的 pass batch，v11 才能进入 `complete`。`action_attempts` 是同一状态内至多八条的动作记录：每条冻结 action、owner 和启动/无进展/绝对时限，且只能按 `intent → running → observed → committed` 推进；只有带运行回执和验证指纹的 observed 结果才能 committed，且 `complete` 前必须至少有一个 committed action。中断或未知结果不能推进 delivery stage，后续 controller 必须先协调真实工件。service runtime 仅支持低风险 route，必须分别冻结非空且不相同的 `verification_argv` 与 `audit_argv`；两者都按 argv 直接执行，不能接受 shell 字符串或模型生成的命令，complete 的 audit receipt 还必须精确匹配 `audit_argv`。service 的每个外部 runner 都必须先追加冻结 launch、再追加匹配 result；失败 verifier 与最终 audit 都必须作为 fail check 保留 Evidence Receipt。旧 v10 继续按原语义运行，绝不被静默改写为 v11。

Review v3 将每次源码版本保存为一个不可变 round：旧 round 永不重写，只有最后一轮必须匹配当前源码，修复后追加新轮。每条内部结果额外保存 `task_id/request_fingerprint`，只能由 `review_contract.py` 对照完整冻结请求生成。adapter 新写入的 finding 结果还在同一 request 保存 `finding_records`：它与 `finding_fingerprints` 一一对应，只含有界 evidence/impact/root_cause 和分类字段；当前 round 的 finding 必须携带 records，历史 round 可只保留 fingerprint，不能伪造详情。普通/高风险完成态要求当前轮同时存在 spec 与 quality pass，quality 初审必须独立盲审，且二者由冻结 external runner 的同名 `profile.worker_id`、完整 canonical request 与 completed available role result 中完全相同的 Review v3 record 证明。reviewer 不进入 native worker registry，也不替代 host 清场。高风险的 spec 也必须独立盲审。integration 是否必需由 frozen profile 推导；必需时初始预算只能为 1，首次 integration 请求在同一转换减为 0。repair fingerprint、re-review/closure 请求也必须分别与对应预算的 1→0 同步，不能无动作消费或重复请求。

`host_sync` 保存宿主能力模式、已确认的 Plan Projection 指纹及可选降级证据。投影由 `delivery_progress.py projection` 确定性生成，覆盖全部合法阶段，未知阶段明确拒绝；步骤名称始终与冻结清单一致，不包含 state revision 或 `host_sync` 本身。`delivery_next.py` 返回 `sync-plan` 后，父控制器先调用宿主原生计划更新，只有宿主返回成功后才能以 `host_observed` 写回同一指纹；`controller_attested` 不能完成 native acknowledgement，`text|legacy_unavailable` 不进入等待循环。blocked 不走普通同步或降级转换；运行时不承诺终态原生展示，不能为显示重新进入执行循环。

原生调用失败、结果未知或恢复后工具缺失时，控制器先告知文字降级，再通过既有 `delivery_state.py write` 在独立 revision 中将 `native → text`，同时把 `acknowledged_fingerprint` 清为 null、`evidence_level` 设为 `controller_attested`，加入 `fallback={reason: failed|unknown|unavailable, evidence_ref: <调用结果或能力观测引用>, disclosure_ref: <用户可见告知引用>}`。两个引用必须非空，控制器负责核对其真实性；它们不是宿主签名或业务通过证据。此转换不得同时推进阶段、改验收或业务事实。降级记录不可改写或删除，同一 run 不自动升回 native；重载沿用 text 并继续原有下一动作。旧的三字段状态仍兼容，初始 text 无需补 fallback。blocked 状态继续只允许既有清场动作，无需降级来绕过停止条件。

异模型 worker 采用 [Worker Runner](worker-runners.md) 的冻结 profile。它的 `runner` receipt 不属于本节 `runtime_binding`、`workers[]` 或 `worker_tree_receipt`：这些字段只接受真实宿主 bridge 的原始观察。当前 package 没有该 bridge，普通 JSON 不会生成 `host_observed` binding。没有宿主 selector/tree receipt 时，runner 结果只能作为待主 controller 复核的外部工作产物，不能把 `runner` 标成 `host_observed` 或用来直接完成状态；需要新上下文时使用 [Capsule Dispatch v1](capsule-dispatch.md)，其 delivery ack 同样不属于这些字段。

## 2. Provider Binding

- workflow provider 只能是 `pdlc-v1` 或 `native-v1`。
- native workflow 可绑定一个 `tdd` stage provider；PDLC workflow 不得再混入其他 TDD provider。
- 每个引用冻结 manifest 绝对路径/fingerprint、版本、角色、task kind、canonical task contract/fingerprint，以及有序 `sources`。
- `sources` 中每项记录 `entrypoint|closure`、manifest 声明的 relative path、真实绝对路径与内容 fingerprint；声明入口必须从 source root 精确解析。stage provider 必须保留唯一真实入口；`entrypoint_candidates/source_fingerprint` 同时匹配。manifest、task contract、实际入口或 closure 任一变化都阻塞。
- `binding_fingerprint` 是完整 binding 的 canonical JSON sha256，恢复时任一来源变化都会阻塞。
- 兼容旧输出的 `engine` 可以由 binding 派生展示，但不能再写入正式状态。

## 3. Worker、Runtime Binding Schema v4 与 Progress Receipt v1

```json
{
  "ref": "<stable host reference>",
  "parent_ref": null,
  "task_id": "<Plan Contract task id or task key>",
  "depth": 1,
  "may_dispatch": false,
  "role": "implementer",
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
    "evidence_level": "controller_attested | host_observed",
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
  "schema_version": 2,
  "observed_revision": 4,
  "observed_at": "2026-08-21T00:00:00Z",
  "runtime_fingerprint": "<sha256>",
  "mode": "tree_query",
  "evidence_level": "host_observed",
  "observation_fingerprint": "<sha256>",
  "registered_refs": ["<worker-ref>"],
  "active_refs": [],
  "unexpected_refs": []
}
```

`role` 只能是冻结 profile 的 `router|scout|specifier|implementer|verifier|adjudicator`，或 host registry 专用的 `pdlc|evaluator|controller-delegate`；`reviewer`、`implementation`、`review` 等别名不进入 native registry。普通 worker 必须由 `delegated` 路由授权。

首次登记 active worker 必须冻结同会话、含 `tree_query` 的 `host_observed` Runtime Binding；跨会话一律手工交接。`negotiate` 的 Binding 一律是 `controller_attested`，只说明控制器观察到什么能力，不能派发、登记或清场。`bind()` 没有 host-observed 参数，只有具体宿主桥接器将完整原始能力观察交给 `bind_observed` 后才可能构造 `host_observed` Binding；Schema v4 同时保存该 observation 与 fingerprint，并要求 capability 列表与 observation 精确一致。之后 Binding 不可替换。清场回执只能由 `runtime_adapter.py receipt` 根据该 Binding 和与 refs/时间完全一致的原始 host tree query 生成；否则 helper 拒绝生成回执。`runtime_fingerprint` 必须匹配。`registered_refs` 必须与 registry 完全一致（顺序不具有语义）；`active_refs` 只能引用 registry 中 worker；任何非空 `unexpected_refs` 必须立即处于 `blocked` state。complete 时两类未清场引用都必须为空；blocked 若存在 worker 或树回执，也必须使用同 revision 回执并精确列出所有仍 working 的引用。blocked 后仍允许用后续 revision 只更新既有 worker 的宿主生命周期和清场回执，不能登记新 worker、改写任务事实或恢复 active。

生成和展示：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_progress.py" event --worker-ref <ref> --event milestone \
  --phase implementing --milestone "目标测试通过" --activity "完成最小实现" \
  --evidence "26 tests passed" --next-action "运行状态迁移测试" < state.json

python3 "$CONVERGE_SKILL_DIR/scripts/delivery_progress.py" observe --worker-ref <ref> \
  --host-status working --evidence "host query: process active" < state.json

python3 "$CONVERGE_SKILL_DIR/scripts/delivery_progress.py" status < state.json
```

父代理负责按不超过约 60 秒的可见节奏向用户转述最新快照；去重指纹同时包含 worker 宿主 lifecycle，working→completed/blocked/interrupted 不得被相同进度文本隐藏。长测试或工具仍在运行时不编造百分比或 ETA。

## 4. Ledger 与阶段

`ledger` 继续保存；所有 fresh/pass 验收必须携带与顶层 `source_fingerprint` 相同的源码指纹。Schema v10 写入 complete 时，每项验收还必须携带 Evidence Receipt v2：由 `evidence_contract.py run` 使用 argv（不经 shell）真实执行，保存退出码、stdout/stderr 摘要、runner/receipt 指纹和完整 Source Receipt v2。只有 `exit_code=0/evidence_level=observed` 且 source 等于顶层 `source_receipt` 才通过。旧 Schema 和 Evidence v1 直接拒绝。`execution_control` 是路由和审查的唯一真源，保存 canonical routing、Review Protocol v3 单轴请求以及剩余 repair/re-review/integration 预算：

- `completed_rounds`：0–2；
- append-only `repair_fingerprints`（Review v3）与 `autonomy_repair_fingerprints`（自治 audit repair）以及 `checks`；两者预算不得互相消费；
- 当前 `acceptance` 及被替换事实的 `acceptance_history`；
- append-only `runner_launches` 与 `runner_results`；本地 launch 的冻结 workspace 必须等于当前 run workspace。`append-runner-launch` 先于外部副作用写入；若 launch 没有对应 result，后续派发必须以执行结果未知阻塞，不能重派。完成的只读 scout/reviewer receipt 必须在同一条 `runner_results` 记录中带有经 `role_result.py` 校验的 `role_result`（launch 指纹、角色、受限 findings/evidence/next action 和结果指纹），但不得包含 prompt 或模型原文；旧 receipt 缺少该结论时不补猜，后续派发改为交接阻塞。存在冻结 launch 时，只有每项返回通过共享回执校验的 `completed` 结果，且每项只读结果齐全，才能写入 `complete`；
- 增量回执所需的 `report_history`。

`host_sync.acknowledged_fingerprint` 与 `ledger.report_history` 只能各自在独立 revision 中更新；确认计划或记录报告时不得同时推进阶段、修改验收或改写其他任务事实。`ledger.tdd_trace` 仅允许保存有界的 TDD/Impact Trace v5；native complete 时其 source、冻结 risk flags 和 criterion 集合必须分别等于当前 Source Receipt、Routing Receipt 与 `ledger.acceptance`，并返回 `pass`。最终验证通过 rerun 刷新该 trace 后才写入，避免旧绿灯、覆盖率或图谱回执完成新源码。`delivery_state.py doctor` 只扫描当前 workspace 与其 Git common-dir 对应的 state 目录；其中无法解析或非对象的 managed JSON 返回一条 `health=blocked` 的诊断（身份字段为 null），使本 workspace 的磁盘损坏不会被恢复检查静默忽略。

交付报告中的 `verified` 范围只能从 `ledger.acceptance` 的 `fresh/pass` 项和 `ledger.checks` 的 `pass` 项派生。`handoff.last_verification` 是 `controller_attested` 自由文本说明，只能作为 note 展示，不能替代结构化验收、检查或 Evidence Receipt，也不能被渲染为“已验证”。

Native 和第三方 TDD 使用：`scope → round-1-build → round-1-semantic-review → verify-round-1（高风险）→ round-2-risk-review → verify-final`。第三方只替换 native workflow 内红绿方法，不绕过 native 的 TDD/Impact Trace v5 completion gate。PDLC workflow 只使用 `pdlc-run`，其细粒度阶段仍由 PDLC 自己保存。终态 complete 必须位于最终阶段并具有全部 fresh/pass 验收证据；blocked 必须提供 `blocked_code/reason`。

## 5. 路径、租约与原子写入

正式根目录固定为 `~/.convergent-delivery/state/`。路径只能由 `repo_id + task_key + run_id` 推导；候选 JSON 只通过 stdin 提交。每次写入必须：

1. 续期两小时 writer lease；
2. 提交完整下一 revision；
3. 在活动 owner 锁内校验 repo/task/run/writer、冻结字段、Provider 和状态转换；
4. 在正式目录创建 `0600` 临时文件，`fsync` 后原子替换。

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_state.py" path --repo <repo> --task-key <task> --run-id <run>
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_state.py" list --workspace <absolute-worktree>
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_state.py" doctor --workspace <absolute-worktree>
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_state.py" write --input - --repo-id <repo> --task-key <task> \
  --run-id <run> --writer-id <writer> --expected-revision <revision>
python3 "$CONVERGE_SKILL_DIR/scripts/autonomy_arm.py" --state <derived-path> --requirement <item> \
  --acceptance <item> --write --lease-root <root> --state-root <state-root> --repo-id <repo> \
  --task-key <task> --run-id <run> --writer-id <writer> --expected-revision <revision>
python3 "$CONVERGE_SKILL_DIR/scripts/autonomy_begin.py" --workspace <absolute-worktree> \
  --scope <relative-path> --requirement <item> --acceptance <criterion> \
  --mode <auto|pdlc|native> --kind <feature|fix|refactor> \
  --task-profile-json '<frozen-profile-json>'
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_state.py" append-runner-launches --input - --repo-id <repo> --task-key <task> \
  --run-id <run> --writer-id <writer> --expected-revision <revision>
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_next.py" --state <derived-path> --run-id <run> \
  --writer-id <writer> --revision <revision>
```

不得把 `/tmp` 文件、调用者指定的任意路径或自然语言回执当作状态真源。workspace 只有在同 owner 的有效 lease move 后才能改变；revision、worker 身份和终态均不可回退。
