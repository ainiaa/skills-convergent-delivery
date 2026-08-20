# 使用与维护指南

Converge Suite 在 Codex 和 Claude Code 中使用同一份源码。安装器只创建软链接，因此升级后两端始终加载同一套规则。

## 支持的运行时

| 运行时 | 安装位置 | 调用方式 |
|---|---|---|
| Codex | `~/.codex/skills/{converge,converge-plan,converge-review,converge-batch}` | 自然语言或对应 `$skill-name` |
| Claude Code | `~/.claude/skills/{converge,converge-plan,converge-review,converge-batch}` | 自然语言或对应 `/skill-name`（以运行时发现结果为准） |

## 前置条件

- 使用远程安装时需要 Bash、`curl`、`git` 和可访问 GitHub 的网络。
- 使用本地 clone 安装时需要 Bash；运行项目检查和状态 helper 需要 Python 3.9 或更高版本。
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

安装后或排查“Skill 没触发”时，先运行只读诊断：

```bash
bash install.sh --doctor --target codex --offline
```

`--doctor` 检查 Suite 四个入口是否来自同一版本、必需文件、Git、Python 和执行引擎，不修改安装。

安装器先预检两个运行时的全部四个目标，再迁移旧入口和创建软链接。任一目标冲突时不会安装或迁移任何入口。普通文件或目录不会被删除；若发现旧名称 `convergent-delivery` 的已知目录，会移动到 `~/.convergent-delivery/legacy-backups/` 后再安装，其他软链接仍必须明确传入 `--force` 才会替换。

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

单任务协调 ledger 保存在两个运行时共用的 `~/.convergent-delivery/state/`。正式路径只能由 helper 推导；Schema v6 冻结 controller/provider，持久化当前 run worker，并继续校验 lease、CAS、冻结契约、阶段与追加证据。旧 v5 第一次写入只添加迁移。PDLC manifest、真实入口或依赖闭包变化会明确阻塞，细节见 [状态 Schema](../references/state-schema.md)。无需恢复的简单任务不创建 state/lease，直接用 `delivery_report.py --input -` 生成报告；持久任务继续使用 `--state`。

Batch 调度状态独立保存在 `~/.convergent-delivery/batch-state/`，使用 Batch Protocol v1 / state Schema v3。reader 可读取旧 v1/v2，下一次写入先做只添加 capsule/task identity、recovery 和 worker lifecycle 的原子迁移；新状态必须是 v3。路径由 repo、`plan_id` 和 `run_id` 推导，另以 `repo_id + plan_id` 建立默认两小时且每次写入续期的 scheduler lease；活动 owner 阻止第二个 run/window，过期后仅允许显式 `--takeover`。`plan_revision` 与 fingerprint 在状态内冻结，任何漂移都会阻塞。写入同样使用 stdin、文件锁、revision CAS、私有临时文件、`fsync` 和同目录原子替换。

## 多窗口并行

可以同时处理多个任务，但每个执行任务应使用独立的 Git worktree 和分支。Skill 在真正写入前自动要求 writer lease：同一 worktree 只能有一个写入者；同一仓库内、范围相同的任务即使位于不同 worktree 也不能重复执行；不同任务在不同 worktree 可以并行。

```bash
# 在主工作区创建一个独立 worktree（示例）
git worktree add ../service-fix -b convergent/fix-payment HEAD
```

Codex 与 Claude Code 共用 `~/.convergent-delivery/leases/` 和 `~/.convergent-delivery/state/`，因此跨运行时既会互斥，也能恢复同一任务。lease 默认两小时。任务每个阶段续期并在终态释放。过期 lease 不会被自动抢占；仅在确认原任务已经停止时，才使用 helper 的 `--takeover`，并在最终报告说明原因。

同一 run 需要切换 worktree（例如从 Codex 转交 Claude Code）时，不要再次 `acquire`。先 `renew`，再执行 `delivery_lease.py move --from-workspace <旧路径> --workspace <新路径>`，并保留原来的 `task-key`、`run-id` 和 `writer-id`；成功后用新 workspace 更新 state。`move` 会保留任务 lease 并释放旧 workspace lease。

PDLC 的 `docs/.pdlc-state/` 继续保存流程状态，但不提供跨窗口互斥。Converge 的 JSON adapter manifest 校验 provider id/version、feature/fix/refactor 入口、授权边界和显式源码闭包；已安装但未适配或冻结后变化会明确阻塞。具体边界见 [TDD 提供者](../references/tdd-providers.md)。

复杂任务先由 `converge-plan` 生成并校验 Plan Contract。PDLC 路径只有一个 `pdlc-run`，宿主支持时完整流程在 fresh context 中执行，否则手工交接；非 PDLC 路径按依赖和 `owned_paths` 生成 wave。每个派发 capsule 都携带并由 Schema 校验 `planned_task=true`、正确 `plan_id/task_id`，避免子执行者再次规划。计划结束后必须把真实 workspace 交给 audit，由 helper 自行读取 Git commit/tree/diff/changed paths 并核对结构化证据。

`converge-batch` 的 scheduler lease 只保护计划调度权，不是代码 writer lease。所有 worker 登记、宿主终态、watchdog、恢复与清场规则以 [执行控制](../references/execution-control.md) 为唯一真源；Batch 只在自身协议中保留 dispatch/receipt/state 的专有字段。

## 维护版本

发布新版本时：

1. 更新 `VERSION`。
2. 在 `CHANGELOG.md` 的 `Unreleased` 中记录面向用户的变更。
3. 运行 `bash scripts/check.sh`，执行安装器、状态 helper、lease、Shell 语法和四个 Skill 的官方 quick_validate。开发依赖锁定在 `requirements-dev.txt`；缺失时 check 必须失败，不全局安装。
4. 提交后创建对应的 Git tag，才将变更日志标记为正式版本。

不要为 Codex 和 Claude Code 复制两份 Skill 源码；如需调整流程，修改仓库中的对应 Skill。旧的 `convergent-delivery` 安装软链接只要指向同一源码，就会在下次安装或升级时自动迁移为 `converge`。
