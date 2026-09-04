# Capsule Dispatch v1 决策记录

本轮受影响的是多代理交接与宿主边界。先以 [Skills.sh agent-workflows](https://www.skills.sh/topic/agent-workflows) 作发现，核对其引出的 [codex-dynamic-workflows 原始 SKILL](https://raw.githubusercontent.com/dannymac180/skills/main/codex-dynamic-workflows/SKILL.md)，再核对 [Codex app](https://openai.com/index/introducing-the-codex-app/)、[Codex exec JSONL event contract](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs)、[Claude Code subagents/background sessions](https://code.claude.com/docs/en/sub-agents)、[Superpowers subagent-driven-development](https://raw.githubusercontent.com/obra/superpowers/main/skills/subagent-driven-development/SKILL.md) 与 [external-subagents](https://github.com/obra/external-subagents) 的原始行为说明。

| 参考 | 采用 / 不采用 | 原因与行为测试 |
| --- | --- | --- |
| Codex Subagents | 采用宿主创建 task 与可见 task id 是宿主事实 | `test_runtime_adapter.py` 证明普通 JSON 不能升级为 host lifecycle。 |
| Codex `exec --json` | 采用首个 `thread.started.thread_id` 作为一次创建的确认 | `test_capsule_dispatch.py` 证明只有该事件才产生 `delivered`。 |
| Claude Code background session | 采用 `--background` 的实际新 session；创建锚点是启动前后 JSON inventory 中的新 name + cwd + id | `test_capsule_dispatch.py` 证明 capsule 先固化为 attempt 私有快照（不进入 argv 正文），且 `claude agents --json --all --cwd` 只回读新出现的同名 session 后才产生 `delivered`。真实 smoke 证明当前 CLI 忽略调用方 `--session-id`，故不再伪造稳定 UUID 或解析人类启动文案。 |
| ChatGPT Desktop subagents | 当前不采用 | 宿主无法强制 child 保持 leaf；`fork_turns` 只能隔离历史。保留不可用边界，直到宿主提供强制 leaf 与后代观察。 |
| Skills.sh / codex-dynamic-workflows | 采用“只在真实宿主 runner 存在时自动派发” | 两个 CLI 适配器分别预检真实 `codex`/`claude` 命令与必需参数；无命令或能力不足为 `unavailable`，不伪造派发。 |
| Superpowers | 采用冻结任务包交给新鲜执行上下文 | `test_delivery_next.py` 继续阻止 worker lifecycle 放行完成。 |
| external-subagents | 采用明确的 launch/delivery 结果与不确定时不重派 | `test_delivery_lease.py` 证明带 worker 的 terminal state 也不能仅凭自写 receipt 释放 lease。 |
| 通用 worker capability profile / 第二个 durable registry | 不采用 | 各宿主的 query、tree、interrupt 语义不可通用；delivery ack 也不足以替代完成回执。复用现有 capsule 与 Single/Batch state。 |

结论：核心只通用 `delivered | unavailable | failed | indeterminate` 的 capsule 投递语义。Codex CLI 和 Claude Code 均已有 concrete successor adapter；投递成功启动 successor，但 successor 必须以自己的源码和验收完成。ChatGPT Desktop 当前缺少强制 leaf，原生 subagent 为 `unavailable`。三者都不提供 query/interrupt/tree/cleanup 的完整可恢复 worker bridge，故 `workers[]` 自动 lifecycle 继续关闭。未来扩展 Batch 前，仍须先提供“successor 写自身 state → 父读取已验证 receipt”的端到端真实链，而不是恢复公共 JSON 的 `host_observed` 入口。

2026-09-04 已在 ChatGPT Desktop 当前会话做无写入 smoke：`spawn_agent` 可创建 child 并返回 ref，但宿主没有强制 child 保持 leaf。该 smoke 不构成 adapter 准入证据。

同日真实 CLI smoke：Codex `exec --json` 返回 `thread.started.thread_id`；Claude `--background` 实际忽略调用方 `--session-id`，但 `claude agents --json --all --cwd` 回读到新建 session。适配器据此只以“启动前后 JSON inventory 的新 name + cwd + id”确认投递。该机器的 Claude worker 随后因 Provider 缺少 `base_url` 退出；这是运行配置失败，不提升或否定 creation receipt。
