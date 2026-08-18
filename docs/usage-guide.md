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

安装器不会删除已有的普通文件或目录。若发现本 Skill 旧名称 `convergent-delivery` 的目录，会先移动到 `~/.convergent-delivery/legacy-backups/` 再安装 `converge`，避免两个版本同时触发；其他软链接仍必须明确传入 `--force` 才会替换。

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

非 PDLC 的跨会话 ledger 保存在两个运行时共用的 `~/.convergent-delivery/state/`。正式路径只能由 `scripts/delivery_state.py path` 推导；更新时将完整 JSON 经 `delivery_state.py write --input -` 的 stdin 提交，脚本不会接受 `/tmp` 候选文件或任意 `--state` 路径。它会校验活动 lease、writer 和 revision。恢复任务前必须运行 `scripts/delivery_next.py` 并传入 `run_id`、`writer_id` 和 `revision`。在 Claude Code 中使用 `${CLAUDE_SKILL_DIR}/scripts/` 定位这些 helper，避免因当前工作目录变化而找不到文件。

## 多窗口并行

可以同时处理多个任务，但每个执行任务应使用独立的 Git worktree 和分支。Skill 在真正写入前自动要求 writer lease：同一 worktree 只能有一个写入者；同一仓库内、范围相同的任务即使位于不同 worktree 也不能重复执行；不同任务在不同 worktree 可以并行。

```bash
# 在主工作区创建一个独立 worktree（示例）
git worktree add ../service-fix -b convergent/fix-payment HEAD
```

Codex 与 Claude Code 共用 `~/.convergent-delivery/leases/` 和 `~/.convergent-delivery/state/`，因此跨运行时既会互斥，也能恢复同一任务。lease 默认两小时。任务每个阶段续期并在终态释放。过期 lease 不会被自动抢占；仅在确认原任务已经停止时，才使用 helper 的 `--takeover`，并在最终报告说明原因。

同一 run 需要切换 worktree（例如从 Codex 转交 Claude Code）时，不要再次 `acquire`。先 `renew`，再执行 `delivery_lease.py move --from-workspace <旧路径> --workspace <新路径>`，并保留原来的 `task-key`、`run-id` 和 `writer-id`；成功后用新 workspace 更新 state。`move` 会保留任务 lease 并释放旧 workspace lease。

PDLC 的 `docs/.pdlc-state/` 继续保存流程状态，但不提供跨窗口写入互斥；执行 PDLC 时同样遵从本 Skill 的 lease 规则。未安装 PDLC 时，直接使用 `converge` 的原生状态机、TDD 和验证规则，不会因此阻塞。

## 维护版本

发布新版本时：

1. 更新 `VERSION`。
2. 在 `CHANGELOG.md` 的 `Unreleased` 中记录面向用户的变更。
3. 运行 `bash scripts/check.sh`，执行安装器、状态 helper、lease、Shell 语法和必要 Skill 元数据检查。
4. 提交后创建对应的 Git tag，才将变更日志标记为正式版本。

不要为 Codex 和 Claude Code 复制两份 `SKILL.md`；如需调整流程，只修改仓库根目录的主文件。旧的 `convergent-delivery` 安装软链接只要指向同一源码，就会在下次安装或升级时自动迁移为 `converge`。
