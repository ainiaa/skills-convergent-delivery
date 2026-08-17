# 使用与维护指南

`converge` 在 Codex 和 Claude Code 中使用同一份 `SKILL.md`。安装器只创建软链接，因此升级后两端始终加载同一套规则。

## 支持的运行时

| 运行时 | 安装位置 | 调用方式 |
|---|---|---|
| Codex | `~/.codex/skills/converge` | 自然语言或 `$converge` |
| Claude Code | `~/.claude/skills/converge` | `/converge` 或自然语言 |

## 前置条件

- 使用远程安装时需要 Bash、`curl`、`git` 和可访问 GitHub 的网络。
- 使用本地 clone 安装时需要 Bash；运行项目检查还需要 Python 3。
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

安装器不会删除已有的普通文件或目录。若目标位置存在其他软链接，必须明确传入 `--force` 才会替换。

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

非 PDLC 的跨会话 ledger 保存位置如下：

| 运行时 | 状态位置 |
|---|---|
| Codex | `~/.codex/state/convergent-delivery/` |
| Claude Code | `~/.claude/state/convergent-delivery/` |

恢复任务前，运行 `scripts/delivery_next.py`。在 Claude Code 中使用 `${CLAUDE_SKILL_DIR}/scripts/delivery_next.py`，避免因当前工作目录变化而找不到 helper。

## 多窗口并行

可以同时处理多个任务，但每个执行任务应使用独立的 Git worktree 和分支。Skill 在真正写入前自动要求 writer lease：同一 worktree 只能有一个写入者；同一仓库内、范围相同的任务即使位于不同 worktree 也不能重复执行；不同任务在不同 worktree 可以并行。

```bash
# 在主工作区创建一个独立 worktree（示例）
git worktree add ../service-fix -b convergent/fix-payment HEAD
```

Codex 与 Claude Code 共用 `~/.convergent-delivery/leases/`，因此跨运行时也会互斥；各自的非 PDLC ledger 仍保存在运行时状态目录。lease 默认两小时。任务每个阶段续期并在终态释放。过期 lease 不会被自动抢占；仅在确认原任务已经停止时，才使用 helper 的 `--takeover`，并在最终报告说明原因。

PDLC 的 `docs/.pdlc-state/` 继续保存流程状态，但不提供跨窗口写入互斥；执行 PDLC 时同样遵从本 Skill 的 lease 规则。恢复时必须传入 `run_id`、`writer_id` 和当前 `revision`，以防旧窗口覆盖新状态。

## 维护版本

发布新版本时：

1. 更新 `VERSION`。
2. 在 `CHANGELOG.md` 的 `Unreleased` 中记录面向用户的变更。
3. 运行 `bash scripts/check.sh`，执行安装器、状态 helper、lease、Shell 语法和必要 Skill 元数据检查。
4. 提交后创建对应的 Git tag，才将变更日志标记为正式版本。

不要为 Codex 和 Claude Code 复制两份 `SKILL.md`；如需调整流程，只修改仓库根目录的主文件。旧的 `convergent-delivery` 安装软链接只要指向同一源码，就会在下次安装或升级时自动迁移为 `converge`。
