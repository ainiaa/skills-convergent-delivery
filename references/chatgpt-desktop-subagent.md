# ChatGPT Desktop Native Subagent v1（当前不可用）

当前工具面可暴露 `spawn_agent`、`wait_agent` 与 `interrupt_agent`，但 child 仍拥有派生代理的能力。宿主没有 `restrict_dispatch` 或等价的强制 leaf 控制，因此当前 package 将原生 child 视为 `unavailable`：不得创建 child，也不得降级到 CLI、消息队列或手工伪造 task id。

`fork_turns: "none"` 只能隔离完整会话，不能强制 child 作为 leaf；`wait_agent` 只是等待事件，`interrupt_agent` 也只能针对已知 ref。文字要求“不得再创建 agent”不能替代宿主控制。

需要新上下文时使用 [Capsule Dispatch v1](capsule-dispatch.md) 的独立 successor；它有自己的 session、run 和验收。当前会话 native child 只有在宿主同时提供强制 leaf、精确 child ref 与可验证的后代观察后，才能作为新 adapter 重新评估；即使如此也不能直接作为跨会话 worker lifecycle 或 Batch receipt。
