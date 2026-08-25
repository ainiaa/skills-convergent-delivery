# Worker Profile 与薄 Runner Registry v1

本协议只在已冻结计划、确有上下文隔离收益的复杂 task 中使用。简单 `inline` task 不创建 profile、runner 或额外进程。

## 不变边界

Controller 在启动前冻结一个 `Worker Profile v1`：`worker_id`、角色、`runner_id`、requested/effective model 与 reasoning effort、权限和有限预算，以及 canonical fingerprint。worker 只能接收该 profile，不能自行换模型、提高 effort、扩大写权限、打开 shell 或增加预算。

`runtime_adapter.py` 仍只表示真实宿主任务树。runner receipt 使用 `evidence_source="runner"`，绝不能写成 `host_observed`、不能伪造 host ref，也不能单独满足现有 Schema v10 的 worker-complete 清场门槛。这样 Codex Desktop host bridge 未公开时，进程 runner 不会被误报为原生宿主集成。

registry 是静态 capability 表，只含两个 adapter，不保存 task graph、队列、memory、状态副本或调度循环。正式状态、租约、计划和完成判定仍归 Converge controller；runner 的计划/执行 receipt 只能被状态引用或作为后续验证输入。

## Profile

```json
{
  "schema_version": 1,
  "worker_id": "research-1",
  "role": "research",
  "runner_id": "openai-compatible-v1",
  "requested": {"model": "glm-5.2", "reasoning_effort": "high"},
  "effective": {"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
  "permissions": {"workspace": "read", "shell": false, "network": "egress"},
  "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 12000},
  "profile_fingerprint": "<sha256>"
}
```

`requested` 是用户/控制器请求；`effective` 是 controller 根据已知 provider capability 解析后冻结的值。OpenAI-compatible runner 还要求一份显式 `effort_binding={"field":"<provider wire field>","value":"<provider value>"}`，例如 `thinking.type=enabled`；没有该映射绝不发送猜测的 `reasoning_effort` 字段。不可在执行中静默替换。`max_turns` 是 controller 的有限派发预算；adapter 强制 timeout，不把不受 CLI/API 支持的输出/轮次限制伪称为 provider 已强制执行。

- `implementation` 可使用 `codex-exec-v1` 的 isolated-worktree 写权限；`reviewer`、`research` 永远不可写。
- `codex-exec-v1` 只接受 `effective.provider=openai`，requested/effective 的 model 与 effort 必须完全相同；它产生 `codex exec --json --sandbox <read-only|workspace-write> -m <model> -c model_reasoning_effort=...` 的精确启动计划。
- `openai-compatible-v1` 仅接受 `reviewer|research`、`workspace=none|read`、`shell=false`。它支持 `deepseek`、`zhipu` 或明确的 `openai-compatible` endpoint；请求没有 tools、shell 或工作区写入能力。

## 真实执行与密钥

两个 adapter 默认只产生 `status=planned` receipt。`codex_exec_runner.execute_launch(..., allow_execute=True)` 才会启动本地 Codex CLI；写权限只能指向独立 Git worktree，父 controller 仍要审查 diff 和运行独立验证。

`openai_compatible_runner.execute_request(..., allow_network=True, effort_binding=...)` 才会发送 HTTPS 请求。调用者在调用边界从环境变量读取 API key 后传入；profile、计划和 receipt 都不保存 key 或 prompt。返回的 `model` 必须精确等于 frozen effective model，否则 adapter 阻断，避免 provider alias/回退被误当成功。

首次 production smoke test 是单独的外发授权：使用非生产 worktree、最小无敏感 prompt、单个 profile 和明确费用上限；其结果只证明该 provider/account 的当时配置，不能替代代码回归测试或 host-native receipt。

## 当前接线状态

`codex-exec-v1` 已可在明确允许后实际启动 CLI；OpenAI-compatible adapter 已可在明确允许后执行一次无工具 HTTPS request（DeepSeek/GLM 通过各自 OpenAI-compatible base URL）。二者当前是受限叶子执行器，不是 Codex Desktop 原生 subagent bridge：没有公开 host capability/tree receipt 时，controller 必须把它们的结果当作外部工作产物并自行核验，不能自动把它们登记为完成的 host worker。
