# 宿主能力边界

| 执行方式 | 可证明能力 | 不可承诺能力 |
|---|---|---|
| 当前 Desktop task | 用户可见、可接管、同一 worktree 顺序写入 | 自动创建子 task 或自动恢复 |
| Desktop worktree task | 用户可见的隔离任务；正式 `threadId` 后可读取；同一宿主 App Server 的 `thread/list` 可按唯一标题、时间窗和可选父 task 解析候选 ID | 自动 worker lifecycle；同名/缺失/无法用 `thread/read` 核验的临时 `clientThreadId` 解析 |
| CLI `codex exec --json` | JSONL `thread.started` 正式 ID、同一 session resume、结构化日志 | 自动出现在 Desktop 侧栏 |
| subagent | 父 task 内的短暂辅助 | 独立 Desktop 会话或独立用户接管 |

临时 Desktop ID 未被宿主解析时记录为 `uncovered`；不读取内部索引猜测 task，也不重发同一任务。CLI runner 只能由用户明确选择，且必须把结构化进度日志和终态回执提供给用户。
