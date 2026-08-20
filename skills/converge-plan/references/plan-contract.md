# Plan Contract v1

## 1. Schema

```json
{
  "schema_version": 1,
  "plan_id": "plan-<stable-id>",
  "requirement_fingerprint": "<lowercase sha256>",
  "engine": "pdlc-v1 | superpowers-tdd-v1 | mattpocock-tdd-v1 | generic-tdd-v1 | native-v1",
  "planner": {
    "name": "project-plan-v1 | superpowers-writing-plans-v1 | generic-plan-v1 | native-plan-v1 | pdlc-delegation-v1",
    "source_path": "<absolute path or null>",
    "source_fingerprint": "<sha256 or null>"
  },
  "context": "short | long",
  "tasks": [
    {
      "task_id": "T1",
      "goal": "one independently testable outcome",
      "owned_paths": ["relative/path"],
      "depends_on": [],
      "steps": ["one action"],
      "acceptance": ["observable behavior"],
      "verification": ["real command"],
      "execution": "auto | current | fresh",
      "status": "pending"
    }
  ],
  "final_acceptance": ["integrated observable behavior"],
  "decisions": []
}
```

任务 ID 唯一，依赖必须存在且无循环；路径必须是工作区内相对路径。一个 task 只对应一个可验证结果，一个 step 只包含一个动作。项目计划或第三方 planner 必须冻结绝对来源路径与内容摘要；内置 planner 不伪造来源。

## 2. PDLC delegation barrier

`engine=pdlc-v1` 时必须且只能有一个 `task_id=pdlc-run`。该 task 使用 fresh context 完整调用 `pdlc-feature` 或 `pdlc-fix`。不得增加 requirements/design/tdd/implementation/review 子任务，也不得在 Converge 中生成等价产物。

## 3. Waves 与执行

`plan_check.py validate` 按显式依赖生成 wave。同一 wave 内的任务还必须保证 `owned_paths` 不相互包含；重叠任务自动进入后续 wave。

- 单个短任务：`current`。
- 单个长任务、长/压缩上下文或 PDLC：`fresh`。
- 多任务：`batch`。wave 标识理论上可并行的候选，但内置 Batch Protocol v1 保持顺序执行；在没有多 worktree 集成和多 receipt 状态协议前，不宣称并行写入能力。

派发 capsule 必须包含 `planned_task=true`。该标记是递归保护：子执行者执行冻结 task 后交回 receipt，不创建新计划、不再派发同一 task。

## 4. 决策记录

可逆技术选择和有明确默认的局部选择自动记录到 `decisions`。业务规则、公共契约、权限、发布或不可逆选择在计划开始前阻塞，一次只询问最高优先级的一项，并给出推荐、原因和影响。

## 5. 完成审计

执行结束后，将以下 envelope 传给：

```bash
python3 "$CONVERGE_PLAN_SKILL_DIR/scripts/plan_check.py" audit --input -
```

```json
{
  "plan": {},
  "source_fingerprint": "<current source sha256>",
  "task_results": {
    "T1": {
      "status": "DONE",
      "fresh_pass": true,
      "verified_source_fingerprint": "<same sha256>",
      "evidence": ["real command and exit result"]
    }
  },
  "final_acceptance": [{
    "criterion": "integrated behavior",
    "result": "pass",
    "freshness": "fresh",
    "evidence": "real integration check",
    "verified_source_fingerprint": "<same sha256>"
  }],
  "changed_paths": ["relative/path"]
}
```

状态语义：

- `DONE`：验收已满足，任务证据非空，且验证源码指纹与当前源码一致。
- `PARTIAL`：只完成部分验收，或通过证据已经陈旧。
- `NOT_DONE`：没有可信完成回执。
- `CHANGED`：经授权改变了原计划目标，必须说明新目标和影响。

不属于任何 `owned_paths` 的变更列入 `scope_drift`。只有所有任务为 `DONE`、没有 `scope_drift`，并且每条计划级 `final_acceptance` 都有绑定当前源码指纹的新鲜通过证据时，才能交付。
