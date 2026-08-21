# Plan Contract v5

## 1. Schema

```json
{
  "schema_version": 5,
  "plan_id": "plan-<stable-id>",
  "requirement_fingerprint": "<lowercase sha256>",
  "planner": {
    "name": "project-plan-v1 | superpowers-writing-plans-v1 | generic-plan-v1 | native-plan-v1 | pdlc-delegation-v1",
    "source_path": "<absolute path or null>",
    "source_fingerprint": "<sha256 or null>"
  },
  "context": "short | long",
  "baseline": {"commit": "<full Git object id>", "source": {"schema_version": 2, "source_fingerprint": "<sha256>", "changed_entries": []}},
  "checkpoint": "same_session | cross_session",
  "tasks": [
    {
      "task_id": "T1",
      "task_kind": "vertical_slice | wide_refactor | integration",
      "outcomes": ["one independently verifiable result"],
      "goal": "one independently testable outcome",
      "owned_paths": ["relative/path"],
      "depends_on": [],
      "steps": ["one action"],
      "acceptance": ["observable behavior"],
      "verification": ["real command"],
      "execution": "auto | current | fresh",
      "status": "pending",
      "provider_run": {"scope": "task", "recursive_planning": false},
      "provider_binding": {
        "controller": "converge",
        "workflow_provider": "<registered workflow Provider id>",
        "stage_providers": {"tdd": "<registered stage Provider id>"},
        "binding_fingerprint": "<lowercase sha256>"
      }
    }
  ],
  "final_acceptance": ["integrated observable behavior"],
  "decisions": []
}
```

任务 ID 唯一，依赖必须存在且无循环；路径必须是工作区内相对路径。`task_kind` 明确区分垂直切片、单结果宽重构和跨任务集成；`outcomes` 必须恰好一个，多个独立结果必须拆成多个 `vertical_slice`。`integration` 必须至少依赖一个前置 task。一个 step 只包含一个动作。`provider_run` 必须严格声明一个 task 范围、禁止递归规划；Provider Binding 摘要必须与 workflow/stage ID 的规范 JSON 一致。项目计划或第三方 planner 必须冻结绝对来源路径与内容摘要；内置 planner 不伪造来源。

旧 v1-v4 继续按兼容协议读取；新 v5 计划必须冻结 Source Receipt v2，不能用当前 `HEAD` 或一个裸 diff hash 伪造任务起点。long context 单任务必须显式声明唯一 outcome，或拆成多个垂直切片。新计划不得再写 `engine` 或旧 schema。

## 2. Provider delegation barrier

每个 task 只冻结一个 workflow provider。`pdlc-v1` task 使用 fresh context，按冻结的 adapter 入口完整调用 `pdlc-feature`、`pdlc-fix` 或 `pdlc-refactor`；`wide_refactor` capsule 必须携带“外部行为不变”验收。不得把 PDLC 内部 requirements/design/tdd/implementation/review 再拆成 Converge task，但可以按独立业务切片形成多个 PDLC-backed task。

PDLC capsule 除 `planned_task/plan_id/task_id` 外，还必须原样携带冻结范围、验收、公共契约和 Converge 决策门禁：业务规则、公共契约、权限、发布及不可逆事项必须停止；provider 的自行假设或自动发布不能提升权限。禁止 `pdlc-ship`、commit、tag、push、publish、install。

## 3. Waves 与执行

`plan_check.py validate` 按显式依赖生成 wave。同一 wave 内的任务还必须保证 `owned_paths` 不相互包含；重叠任务自动进入后续 wave。

- 单个短任务：`current`。
- 单个长任务、长/压缩上下文或 PDLC：`fresh`。
- `checkpoint=same_session` 的多任务：`sequential`，按 wave 顺序执行，`commit_authorization_required=false`。
- 只有显式 `checkpoint=cross_session`：`batch`，`commit_authorization_required=true`；在 checkpoint 前单独请求一次本地 commit 授权。该授权不包含 push、merge、tag 或发布。

wave 标识理论上可并行的候选；当前共享工作区仍顺序执行，不宣称并行写入能力。任务数量本身不能推导 commit 权限。

派发 capsule 必须包含 `planned_task=true` 和当前 task 的 Provider Binding。该标记是递归保护：子执行者执行冻结 task 后交回 receipt，不创建新计划、不再派发同一 task。

每个 capsule 还必须原样携带本计划的 `plan_id` 和当前任务的 `task_id`。Batch state helper 会把三者作为 Schema 字段校验，不能只依赖提示词约定。

## 4. 决策记录

可逆技术选择和有明确默认的局部选择自动记录到 `decisions`。业务规则、公共契约、权限、发布或不可逆选择在计划开始前阻塞，一次只询问最高优先级的一项，并给出推荐、原因和影响。

## 5. 完成审计

执行结束后，将以下 envelope 传给：

```bash
python3 "$CONVERGE_PLAN_SKILL_DIR/scripts/plan_check.py" audit --workspace "$PWD" --input -
```

```json
{
  "plan": {},
  "task_results": {
    "T1": {
      "status": "DONE",
      "fresh_pass": true,
      "source_before": {"schema_version": 2, "source_fingerprint": "<task start>"},
      "source_after": {"schema_version": 2, "source_fingerprint": "<task end>"},
      "evidence": [{
        "schema_version": 1,
        "command": "real verification command",
        "exit_code": 0,
        "source": {
          "schema_version": 2,
          "baseline_commit": "<plan baseline commit>",
          "commit_id": "<Git HEAD>",
          "tree_hash": "<HEAD tree>",
          "diff_fingerprint": "<workspace diff sha256>",
          "changed_paths": ["relative/path"],
          "changed_entries": [{"path": "relative/path", "kind": "file", "mode": "100644", "content_fingerprint": "<sha256>"}],
          "source_fingerprint": "<receipt sha256>"
        }
      }]
    }
  },
  "final_acceptance": [{
    "criterion": "integrated behavior",
    "result": "pass",
    "freshness": "fresh",
    "evidence": {
      "schema_version": 1,
      "command": "real integration check",
      "exit_code": 0,
      "source": {
        "schema_version": 2,
        "baseline_commit": "<same plan baseline commit>",
        "commit_id": "<same Git HEAD>",
        "tree_hash": "<same HEAD tree>",
        "diff_fingerprint": "<same workspace diff sha256>",
        "changed_paths": ["relative/path"],
        "changed_entries": [{"path": "relative/path", "kind": "file", "mode": "100644", "content_fingerprint": "<sha256>"}],
        "source_fingerprint": "<same receipt sha256>"
      }
    }
  }]
}
```

`audit` 自己从 `--workspace` 读取真实 Git `HEAD`、tree、`git diff <baseline>` 和未跟踪文件，计算 Source Receipt Schema v2；receipt 同时绑定路径、文件/符号链接/删除类型、执行权限和内容摘要，非 UTF-8 路径明确阻塞。v5 以冻结 baseline receipt 为游标，逐个核对 task 的 `source_before/source_after` 连续性和 `owned_paths` 增量，任务开始前已有脏文件不会被误算为本任务改动。helper 只运行固定的只读 Git 子命令；Evidence Receipt Schema v1 中的 `command` 只作为已执行证据描述校验，绝不由 audit 执行。

状态语义：

- `DONE`：验收已满足，任务证据为退出码 0 的结构化 receipt，且 receipt source 与该 task 的 `source_after` 完全一致。
- `PARTIAL`：只完成部分验收，或通过证据已经陈旧。
- `NOT_DONE`：没有可信完成回执。
- `CHANGED`：经授权改变了原计划目标，必须说明新目标和影响。

每个 task 新增但不属于自身 `owned_paths` 的变更列入 `task_scope_drift`；所有 task 之外的净新增变更列入 `scope_drift`。只有源码链闭合到当前工作区、所有任务为 `DONE`、两类 drift 均为空，并且每条计划级 `final_acceptance` 都有绑定当前源码指纹的新鲜通过证据时，才能交付。
