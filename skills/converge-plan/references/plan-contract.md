# Plan Contract v4

## 1. Schema

```json
{
  "schema_version": 4,
  "plan_id": "plan-<stable-id>",
  "requirement_fingerprint": "<lowercase sha256>",
  "planner": {
    "name": "project-plan-v1 | superpowers-writing-plans-v1 | generic-plan-v1 | native-plan-v1 | pdlc-delegation-v1",
    "source_path": "<absolute path or null>",
    "source_fingerprint": "<sha256 or null>"
  },
  "context": "short | long",
  "baseline": {"commit": "<full Git object id>", "diff_fingerprint": "<sha256>"},
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

旧 v1/v2 只有在调用者显式提供真实 baseline 时才可迁移为 v4；v3 缺少 baseline 时明确阻塞，不能用当前 `HEAD` 伪造任务起点。long context 单任务必须显式声明唯一 outcome，或拆成多个垂直切片。新计划不得再写 `engine` 或旧 schema。

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
      "evidence": [{
        "schema_version": 1,
        "command": "real verification command",
        "exit_code": 0,
        "source": {
          "schema_version": 1,
          "baseline_commit": "<plan baseline commit>",
          "commit_id": "<Git HEAD>",
          "tree_hash": "<HEAD tree>",
          "diff_fingerprint": "<workspace diff sha256>",
          "changed_paths": ["relative/path"],
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
        "schema_version": 1,
        "baseline_commit": "<same plan baseline commit>",
        "commit_id": "<same Git HEAD>",
        "tree_hash": "<same HEAD tree>",
        "diff_fingerprint": "<same workspace diff sha256>",
        "changed_paths": ["relative/path"],
        "source_fingerprint": "<same receipt sha256>"
      }
    }
  }]
}
```

`audit` 自己从 `--workspace` 读取真实 Git `HEAD`、tree、`git diff <baseline>` 和未跟踪文件，计算 Source Receipt Schema v1 与 `changed_paths`；已提交和未提交变更都不会因中途 commit 消失。Git 返回的相对路径保持原生字节语义，文件名中的反斜杠不会按调用者路径规则改写成 `/`。调用者提供的同名顶层字段不会成为真源。helper 只运行固定的只读 Git 子命令；Evidence Receipt Schema v1 中的 `command` 只作为已执行证据描述校验，绝不由 audit 执行。

状态语义：

- `DONE`：验收已满足，任务证据为退出码 0 的结构化 receipt，且 receipt source 与 audit 读取的当前工作区完全一致。
- `PARTIAL`：只完成部分验收，或通过证据已经陈旧。
- `NOT_DONE`：没有可信完成回执。
- `CHANGED`：经授权改变了原计划目标，必须说明新目标和影响。

不属于任何 `owned_paths` 的变更列入 `scope_drift`。只有所有任务为 `DONE`、没有 `scope_drift`，并且每条计划级 `final_acceptance` 都有绑定当前源码指纹的新鲜通过证据时，才能交付。
