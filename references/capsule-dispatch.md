# Capsule Dispatch v1

Capsule Dispatch 解决的是“把冻结任务交给一个新 task”的问题，不解决“观察、恢复或清理旧 worker”的问题。它不依赖 `runtime_binding`、`workers[]`、`worker_tree_receipt` 或 watchdog。

## 共同语义

控制器先从已冻结的计划或当前 run 裁剪出 capsule；不能复制完整会话，也不能由接收方重新规划。宿主适配器只能报告下列一种结果：

| 结果 | 必填信息 | 含义 |
| --- | --- | --- |
| `delivered` | adapter、稳定的 external task id | 宿主已接受 capsule，创建了独立 task。 |
| `unavailable` | adapter、原因 | 本会话没有创建 task 的真实 API。 |
| `failed` | adapter、原因 | 创建调用有确定失败结果。 |
| `indeterminate` | adapter、attempt id、原因 | 调用可能已被宿主接受，但尚未取得创建确认；绝不自动重派。 |

`delivered` 只是投递确认，不是 worker 的运行、完成、可恢复、可中断或已清场证明。它不能完成父 run、通过验收、释放含 worker 的 lease，或允许父 run 把 successor 写进 `workers[]`。successor 用自己的 run、源码和验收证据独立完成。

不确定调用结果不是 `delivered`：不重派，保留 capsule 并以 `blocked` 交接，避免产生两个执行者。没有真实创建 API 时，输出同一份 capsule 供用户启动；这只是最后降级，而不是默认语义。

## 宿主适配

适配器只负责一次实际的“创建 task 并传入 capsule”调用，并保留宿主返回的 id。核心不使用 profile 名称判断能力，也不维护另一套 task registry。宿主自己的授权/创建-task 限制仍然优先。

## 已实现的宿主适配器

`scripts/capsule_dispatch.py` 是唯一执行入口。调用方先把**已冻结**的 capsule 写到受控文件；它不会把 capsule 正文写入 receipt。默认 attempt id 由 `host + workspace + capsule` 决定，所以重跑同一输入会复用回执，不会创建第二个 task；确需重新授权一次派发时才显式给新的 `--attempt-id`。

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/capsule_dispatch.py" \
  --host <codex|claude> --workspace "$PWD" --capsule-file <frozen-capsule-file> \
  --receipt-dir <run-artifacts>/capsule-dispatch
```

只有控制器将在投递后停止改动同一 workspace、并让 successor 自己创建 run 时才可调用。`delivered` 之后父控制器仍必须保持 `blocked`/交接，不得据此写 `complete` 或释放任何 worker lease。

| 宿主 | 实际调用 | `delivered` 的判据 | 不确定时 |
| --- | --- | --- | --- |
| Codex CLI | `codex exec --json -C <workspace> -` | JSONL 首个有效 `thread.started.thread_id` | 记录 attempt 与 JSONL；不重派。 |
| Claude Code | `claude --background --name <attempt-unique-name> --append-system-prompt-file <attempt-snapshot> <fixed-prompt>` | 启动前后以 `claude agents --json --all --cwd` 比较；只接受本次新出现且 name、workspace 均匹配的 agent；`sessionId` 存在时作为 external task id | 查询不到精确新 agent 时记录 `indeterminate`；不重派。 |

这两个命令创建的是宿主自己的独立 session/task，不是 `spawn_agent`，也不是同一 session 的消息队列。Codex 的 `queue` 仍只用于向现有 session 追加消息，不能当作 successor adapter。

Claude 的后台模式与 `--print` 互斥，且当前 CLI 忽略调用方给出的 `--session-id`；不得解析其人类展示文案。适配器把已读入并 fingerprint 的 capsule 写成 receipt 同目录、attempt 专属且权限为 `0600` 的快照，再将该快照作为 `--append-system-prompt-file` 输入，并只在 argv 中传固定短提示，避免正文暴露给进程列表或在读入后被替换。快照是该 attempt 的冻结交接产物，不写进 JSON receipt，并保留至上层按交接保留策略清理。派发前会调用 CLI 的 `--help` 做无副作用 capability preflight：Codex 必须声明 `exec --json`；Claude Code 必须声明 `--background`，并接受 `--append-system-prompt-file`，其 `agents` 子命令还必须声明 `--json --all --cwd`。预检不通过为 `unavailable`，不会尝试创建 task。

当前 Batch Protocol 的顺序、跨 checkpoint receipt 链仍需要其已有的 delegate-state 验证；不能把 Capsule Dispatch v1 的 delivery ack 冒充 Batch worker receipt。等某个宿主把“创建 successor → successor 写自身 state → 父读取已验证 receipt”的完整链路作为真实 API 暴露后，再以该宿主适配器单独接入 Batch。
