# Worker Profile 与薄 Runner Registry v1

本协议只在已冻结计划、确有上下文隔离收益的复杂 task 中使用。简单 `inline` task 不创建 profile、runner 或额外进程。

## 不变边界

Controller 在启动前冻结一个 `Worker Profile v1`：`worker_id`、角色、`runner_id`、requested/effective model 与 reasoning effort、权限和有限预算，以及 canonical fingerprint。worker 只能接收该 profile，不能自行换模型、提高 effort、扩大写权限、打开 shell 或增加预算。

`runtime_adapter.py` 仍只表示真实宿主任务树。runner receipt 使用 `evidence_source="runner"`，绝不能写成 `host_observed`、不能伪造 host ref，也不能单独满足现有 Schema v10 的 worker-complete 清场门槛。这样 Codex Desktop host bridge 未公开时，进程 runner 不会被误报为原生宿主集成。

registry 是静态 capability 表，只含三个 adapter，不保存 task graph、队列、memory、状态副本或调度循环。正式状态、租约、计划和完成判定仍归 Converge controller；runner 的计划/执行 receipt 只能被状态引用或作为后续验证输入。

## Profile

```json
{
  "schema_version": 1,
  "worker_id": "scout-1",
  "role": "scout",
  "runner_id": "openai-compatible-v1",
  "requested": {"model": "glm-5.2", "reasoning_effort": "high"},
  "effective": {"provider": "zhipu", "model": "glm-5.2", "reasoning_effort": "high"},
  "permissions": {"workspace": "read", "shell": false, "network": "egress"},
  "budget": {"max_turns": 1, "timeout_seconds": 120, "max_output_chars": 12000},
  "profile_fingerprint": "<sha256>"
}
```

`requested` 是用户/控制器请求；`effective` 是 controller 根据已知 provider capability 解析后冻结的值。OpenAI-compatible runner 还要求一份显式 `effort_binding={"field":"<provider wire field>","value":"<provider value>"}`，例如 `thinking.type=enabled`；没有该映射绝不发送猜测的 `reasoning_effort` 字段。不可在执行中静默替换。`max_turns` 是统一的 controller 规划预算：Claude CLI 以 `--max-turns` 强制它，当前 Codex CLI 不支持该参数，因而 Codex 只强制 timeout 与输出字节上限。`max_output_chars` 兼容既有 Profile v1 名称，但 adapter 按 UTF-8 输出字节上限执行；不把不受 CLI/API 支持的输出/轮次限制伪称为 provider 已强制执行。

- 七个固定角色为 `router`、`scout`、`specifier`、`implementer`、`verifier`、`reviewer` 与 `adjudicator`。只有 `implementer` 可使用独立 worktree 写入；其他角色的 `shell=false` 表示没有可写工作区的 shell 能力。Codex 的 read-only sandbox 仍可执行只读命令，Claude 则只启用 `Read,Grep,Glob`，不能把二者误称成同一种“完全没有 shell”。
- `codex-exec-v1` 与 `claude-code-v1` 都是本地进程 runner，分别只接受 OpenAI 与 Anthropic 的 effective provider，且 requested/effective 的 model 与 effort 必须完全相同。计划冻结 CLI 绝对路径及内容指纹，执行前再次验证；prompt 仅经标准输入传递，不进入命令参数。Codex 读取用户的 `$CODEX_HOME/config.toml`，并冻结其内容指纹；计划后该文件变化会在启动前阻断，而冻结的 `--model`、reasoning effort 与 sandbox 参数仍优先。Claude 显式传入 `--bare --strict-mcp-config --model --effort --max-turns`、冻结工具与 permission mode。Claude 这是一层 CLI permission 边界，不是 OS sandbox。
- `openai-compatible-v1` 仅接受 `reviewer|scout`、`workspace=none|read`、`shell=false`。当前仅支持已验证的 Zhipu origin、`GLM_API_KEY` 与注册的 effort mapping；请求没有 tools、shell 或工作区写入能力。未验证 provider 不发送猜测的 wire 字段。

本地 runner 在每次生成命令时禁止 CLI 原生派发：Codex 覆盖 `agents.enabled=false`、`features.multi_agent=false` 和 `features.multi_agent_v2=false`；Claude 使用 `--disallowedTools Agent,Task,TeamCreate`，保留实施所需的 Bash/Edit/Write 和只读工具。前者覆盖现行配置及 feature 开关，后者同时拒绝 Agent 与旧 Task 派发名称。参数依据：[Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)、[Claude CLI](https://code.claude.com/docs/en/cli-reference)。这不等于禁止通过 shell 或 MCP 访问所有外部服务：Codex 仍继承用户 MCP 配置，工具收窄需先映射任务必要能力；不能把文件系统 read-only sandbox 当成外部 MCP 写操作隔离。

## 真实执行与密钥

stdout/stderr 读取或进度回调异常必须传回共享执行函数，终止并回收本次进程，返回 `unknown` 和异常类型，且不交付已读取的部分回答。读取线程结束本身不能证明流已完整读取；输出超限时清理失败也不得伪装成成功。

三个 adapter 默认只产生 `status=planned` receipt。正式多模型执行使用 `runner_lifecycle.py`：它从 managed state 取得唯一 workspace，先以 `append-runner-launch` 持久化 launch，再执行，最后以 `append-runner-result` 持久化 receipt。runner 对当前 controller 额外返回 `output={status,content?}`：`content` 只在完成且成功提取最终模型文本时存在，受冻结输出预算限制，绝不写入 ledger；`unavailable` 不是可用协作结论。两个本地 runner 的 prompt 写入与 stdout/stderr drain 并发启动，随后立即进入冻结 timeout；子进程不读 stdin 时也会 kill/reap 并写入终态 receipt。输出上限是本地读取到超限后终止的保守边界，不宣称能限制远端在 pipe 中已经写出的字节。receipt 本身只含 exit code、stdout/stderr 摘要、requested model/effort 和有限 timeout/output budget；requested 字段只证明命令请求，并非远端模型观察。写权限只能指向独立 Git worktree，父 controller 仍要审查 diff 和运行独立验证。

`openai_compatible_runner.execute_request(..., allow_network=True)` 才会发送 HTTPS 请求。它只从冻结的 `api_key_env` 环境变量读取 key；profile、计划和 receipt 都不保存 key 或 prompt。返回的 `model` 必须精确等于 frozen effective model，否则 adapter 阻断，避免 provider alias/回退被误当成功。Runner Receipt v2 的 `attestation.model` 明确区分：本地 CLI 只有 `requested`，HTTPS provider 返回并匹配模型时才是 `observed`，未知或失败时为 `unavailable`；`attestation.usage` 只复制可验证的 provider usage，绝不估算 token 或成本。

首次 production smoke test 是单独的外发授权：使用非生产 worktree、最小无敏感 prompt、单个 profile 和明确费用上限；其结果只证明该 provider/account 的当时配置，不能替代代码回归测试或 host-native receipt。`multi_model_smoke.py` 默认只输出 planned；传入 `--allow-execute` 后才会创建 detached 临时 worktree、运行一个只读 scout，并返回不含 prompt/原始回答的脱敏 receipt。

`multi_model_repo_eval.py` 是冻结的两题 Git 小型代码评测。默认只输出 planned；显式 `--allow-execute` 后，它在内部临时 Git 仓库为每题创建 candidate worktree，只让 implementer 写入，先冻结模型改动范围、再以固定 argv 运行 unittest。`--mode multi` 仅在实现与独立验证都通过且范围未越界后增加一个只读 reviewer；review 不会替代确定性验证或改变通过结论。报告只保留 task id、profile/receipt 指纹、验证状态、耗时、变更路径和受限 review 结论，不保留 prompt、源码、原始回答、密钥或成本估算。

两个本地 runner 在主进程正常或非零退出后也会终止本次进程组内的残留子进程；清理失败返回 `unknown`，不能报告完成。该边界覆盖仍属于原进程组的后台进程，不保证清理由自行创建新 session/process group 的进程或宿主外部服务。

`--compare-report` 只能比较同一 task/evaluator fingerprint、相同且唯一的任务 ID 集合；任务数量、结果状态与 summary 必须一致，拒绝缺项、重复、跨题库、跨 evaluator、重复模式及单份报告内混合计划和执行结果。它分别汇总整题耗时与验证耗时；旧报告缺少整题耗时时保留为空，不补零或估算 token/价格。

这项评测衡量单写入及追加只读审查的执行情况和耗时；reviewer 不参与失败实现的修复，因此不能证明多模型提高修复成功率。模型、推理等级或预算不同的报告也不能把差异归因于拓扑；核对原报告的冻结 profile。闭环收益应由既有有限修复流程的同题对照验证，不另建评测专用修复循环。

## 当前接线状态

`codex-exec-v1` 与 `claude-code-v1` 已可在明确允许后实际启动 CLI；OpenAI-compatible adapter 已可在明确允许后执行一次无工具 Zhipu HTTPS request。三者当前都是受限叶子执行器，不是宿主原生 subagent bridge：没有公开 host capability/tree receipt 时，controller 必须把它们的结果当作外部工作产物并自行核验，不能自动把它们登记为完成的 host worker。

`role_dispatch.py` 是 runner 与动态角色流之间的确定性派发计划器。它对所有 agent profile 都输出 `external_runner`，`runner_lifecycle.py` 消费该冻结 profile 并通过 `runner_launch.py` 构造 launch/本地命令或批准的 HTTPS request；因此不会继承父代理模型，也不会把计划冒充为宿主任务树或完成回执。

reviewer 执行某个冻结 Review v3 请求时，controller 必须以单任务 `--review-request-file` 或 fan-out `--review-requests-file` 提供完整 canonical request，避免将验收或范围置入 argv。lifecycle 使用同一 `review_contract.py` 归一化并重算 SHA-256，且要求 task、baseline commit 与 source fingerprint 均匹配当前 managed run；可选的 `--review-request-fingerprint(s)` 只作为相等性断言。三个 runner 将完整 request 和其指纹冻结在 launch configuration，命令与 HTTPS body 不消费该 configuration；非 reviewer、缺 request 或不匹配值确定性拒绝。模型输出只在内存中归一化为 Review v3 record，并作为完成 receipt 的 role result 保存；完成门禁要求其与当前 state request 完全一致。identity 必须是外部 runner 的冻结 `profile.worker_id`，绝不声称为 host-native worker。

所有 runner 都以相同的低层 `output` 语义把响应文本即时返回给当前调用者；它不是 receipt、持久状态或通过依据。`runner_lifecycle.py` 不向 controller 暴露该原文：只读 scout/reviewer 必须经 `role_result.py` 转为与 launch 绑定的受限 JSON 结论，其他角色或不合规输出只返回明确状态。正式 runner receipt 始终只保留回执和指纹，不存 prompt、密钥、原文或审计 transcript。见 [多模型协作](multi-model.md)。

当 controller 证明多个只读任务独立时，可使用 `role_fanout.py` 以最多三个 frozen launch 做 fan-out/fan-in。它仍复用同一 `runner_launches/runner_results` ledger：launch 组必须先原子写入，之后才能启动任何 runner；fan-in 只稳定汇总每项带指纹的 `role_result`，不形成消息总线、共享任务队列或第二状态机。
