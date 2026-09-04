# 使用与维护指南

Converge Suite 在 Codex 和 Claude Code 中使用同一份源码。安装器只创建软链接，因此升级后两端始终加载同一套规则。

## 支持的运行时

| 运行时 | 安装位置 | 调用方式 |
|---|---|---|
| Codex | `~/.codex/skills/{converge,converge-plan,converge-review,converge-batch,converge-eval,converge-autonomy,converge-multimodel}` | 自然语言或对应 `$skill-name` |
| Claude Code | `~/.claude/skills/{converge,converge-plan,converge-review,converge-batch,converge-eval,converge-autonomy,converge-multimodel}` | 自然语言或对应 `/skill-name`（以运行时发现结果为准） |

## 前置条件

- 使用远程安装时需要 Bash、`curl`、`git` 和可访问 GitHub 的网络。
- 使用本地 clone 安装时需要 Bash；运行项目检查和状态 helper 需要 Python 3.9 或更高版本。
- 只有执行全量收口审计时才需要 `codegraph`；`--doctor` 会显示 CodeGraph 是否可用。
- 安装器不需要 `codex` 或 `claude` 命令行工具，但对应运行时必须已安装才能使用 Skill。
- 已打开的 Codex 或 Claude Code 需要重启，或按各自的 Skill 刷新机制重新加载。

## 安装与升级

从本地 clone 安装：

```bash
bash install.sh --target all
```

只安装一个运行时时，将 `all` 改为 `codex` 或 `claude`。远程安装会将源码保存到 `~/.convergent-delivery/source`；升级时运行：

```bash
bash install.sh --upgrade --target all
```

默认会注册全部七个 Skill，便于宿主发现和显式调用；这不会安装 Stop Hook、启动 service 或执行任何模型。`converge-autonomy` 与 `converge-multimodel` 仍只在用户明确请求时触发。只有需要自治续跑时，才执行 `bash install.sh --target <codex|claude> --autonomy` 启用对应 Stop Hook；多模型不需要额外安装步骤。

安装后或排查“Skill 没触发”时，先运行只读诊断：

```bash
bash install.sh --doctor --target codex --offline
```

`--doctor` 检查 Suite 七个入口是否来自同一版本、必需文件、Git、Python、CodeGraph 可用性和 Provider 解析，不修改安装。

安装器先预检两个运行时的全部七个目标，再迁移旧入口和创建软链接。任一目标冲突时不会安装或迁移任何入口。普通文件或目录不会被删除；若发现旧名称 `convergent-delivery` 的已知目录，会移动到 `~/.convergent-delivery/legacy-backups/` 后再安装，其他软链接仍必须明确传入 `--force` 才会替换。

### 常见问题

- **安装被拒绝：已有目录或文件**：先检查该目录是否有自己的修改；迁移或删除它后重试。不要对普通目录使用 `--force`。
- **Skill 未出现**：确认目标路径存在，再重启运行时；Claude Code 也可用 `/skills` 检查发现结果。
- **版本检查显示 `unable to fetch`**：本地安装不受影响；检查网络或使用 `--offline` 仅查看本地版本。
- **提示 `another installation is in progress`**：另一个安装、升级或卸载正在修改运行时入口。等待其结束后重试；确认没有进程在运行后，才人工清理 `~/.convergent-delivery/.install.lock`。

## 版本、卸载和状态

```bash
# 显示本地源码、两端已安装版本及 GitHub main 中的版本
bash install.sh --version

# 不访问网络的版本检查
bash install.sh --version --offline

# 只移除运行时入口；保留受管理源码
bash install.sh --uninstall --target all
```

单任务协调 ledger 保存在两个运行时共用的 `~/.convergent-delivery/state/`。Schema v10 冻结 controller、Provider、路由、Review v3 源码轮次与宿主计划确认，并绑定 Source Receipt v2、worker 进度和清场回执；只有成功状态写入才续期 writer lease。无 worker 的旧状态可保守迁移，旧 worker 状态必须人工恢复。无需恢复的简单任务不创建正式 state，仍使用轻量 writer lease。异模型 leaf 使用 [Worker Runner](../references/worker-runners.md) 的冻结 profile；其 receipt 不是宿主 tree evidence，必须由 controller 复核。

Batch 调度状态独立保存在 `~/.convergent-delivery/batch-state/`，使用 Batch Protocol v1 / state Schema v4 / Receipt v4。路径仅由 repo 与 `plan_id` 推导；run takeover 在同一文件转移 owner。Receipt 从派生的正式 delegate state 读取真源并校验完整 Provider Binding、Source Receipt v2 与 Git 前序链，不接受内嵌自证状态。

## 多窗口并行

可以同时处理多个任务，但每个执行任务应使用独立的 Git worktree 和分支。Skill 在真正写入前自动要求 writer lease：同一 worktree 只能有一个写入者；同一仓库内、范围相同的任务即使位于不同 worktree 也不能重复执行；不同任务在不同 worktree 可以并行。

```bash
# 在主工作区创建一个独立 worktree（示例）
git worktree add ../service-fix -b convergent/fix-payment HEAD
```

Codex 与 Claude Code 共用 `~/.convergent-delivery/leases/` 和 `~/.convergent-delivery/state/`，因此跨运行时既会互斥，也能恢复同一任务。lease 默认两小时。任务每个阶段续期并在终态释放。过期 lease 不会被自动抢占；仅在确认原任务已经停止时，才使用 helper 的 `--takeover`，并在最终报告说明原因。

同一 run 需要切换 worktree（例如从 Codex 转交 Claude Code）时，不要再次 `acquire`。先 `renew`，再执行 `delivery_lease.py move --from-workspace <旧路径> --workspace <新路径>`，并保留原来的 `task-key`、`run-id` 和 `writer-id`；成功后用新 workspace 更新 state。`move` 会保留任务 lease 并释放旧 workspace lease。

PDLC 的 `docs/.pdlc-state/` 继续保存内部流程状态，但不接管 Converge 的跨窗口互斥和外层完成判定。Provider Schema v2 统一校验 PDLC、第三方 TDD 和 Native 的身份、能力、授权、输出及源码闭包。具体边界见 [TDD 提供者](../references/tdd-providers.md)。

复杂任务先由 `converge-plan` 生成并校验 Plan Contract v6。任务按独立业务切片和 `owned_paths` 生成 wave，每个 task 冻结 Provider Binding 与 Source Receipt v2 baseline；计划结束后 audit 逐 task 核对 `source_before/source_after`、自身范围增量、完整收口矩阵和实际 argv 执行产生的 observed Evidence Receipt v2。

子代理在阶段变化、客观产物产生和长命令前后发送 Progress Receipt；父代理只保存最新快照并负责用户可见更新。heartbeat 不计为新客观进展，进度展示不使用百分比或 ETA，也不替代验证证据。

`converge-batch` 的 scheduler lease 只保护计划调度权，不是代码 writer lease。所有 worker 登记、宿主终态、watchdog、恢复与清场规则以 [执行控制](../references/execution-control.md) 为唯一真源；Batch 只在自身协议中保留 dispatch/receipt/state 的专有字段。

Controller Snapshot 默认只冻结核心控制面；需要能力时重复传入 `--extension autonomy` 或 `--extension multimodel`。Hook 自治只选择 `autonomy`；service 自治同时选择 `multimodel` 与 `autonomy`。完整自治轨迹只在开发/发布时额外选择内部 `--extension autonomy-eval`，不会进入普通自治 run。扩展只控制 Skill 发现和冻结执行面，安装仍保留同一个 Suite 源码 checkout。快照中不能直接执行测试脚本，受保护的自治评测只由带 `autonomy-eval` 的快照内评测器按其固定题库启动。

## 维护版本

发布新版本时：

1. 更新 `VERSION`。
2. 在 `CHANGELOG.md` 的 `Unreleased` 中记录面向用户的变更。
3. 运行 `bash scripts/check.sh`，执行安装器、核心状态 helper、lease、Shell 语法和五个核心 Skill 的官方 quick_validate；默认只保留扩展边界的共享契约，不运行自治、多模型扩展的 validator 或运行时回归。发布前运行 `bash scripts/check.sh --full`，它额外验证两个扩展并执行完整自治轨迹。开发依赖锁定在 `requirements-dev.txt`；缺失时 check 必须失败，不全局安装。
4. 提交后创建对应的 Git tag，才将变更日志标记为正式版本。

当前 package 不提供 native worker bridge，`workers[]` 自动 lifecycle 始终关闭；不得把 `spawn_agent`、查询、wait 或消息回执解释为可恢复或跨会话能力。需要换新上下文时优先按 `references/capsule-dispatch.md` 用宿主实际创建任务 API 自动投递冻结 capsule；没有该 API 才输出 capsule 供用户启动。投递确认不等于执行完成，也不允许写入 worker registry。

不要为 Codex 和 Claude Code 复制两份 Skill 源码；如需调整流程，修改仓库中的对应 Skill。旧的 `convergent-delivery` 安装软链接只要指向同一源码，就会在下次安装或升级时自动迁移为 `converge`。
