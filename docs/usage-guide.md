# 使用与维护指南

`convergent-delivery` 在 Codex 和 Claude Code 中使用同一份 `SKILL.md`。安装器只创建软链接，因此升级后两端始终加载同一套规则。

## 支持的运行时

| 运行时 | 安装位置 | 调用方式 |
|---|---|---|
| Codex | `~/.codex/skills/convergent-delivery` | 自然语言或 `$convergent-delivery` |
| Claude Code | `~/.claude/skills/convergent-delivery` | `/convergent-delivery` 或自然语言 |

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

## 版本、卸载和状态

```bash
# 显示本地源码、两端已安装版本及 GitHub 最新版本
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

## 维护版本

发布新版本时：

1. 更新 `VERSION`。
2. 在 `CHANGELOG.md` 记录面向用户的变更。
3. 运行 `python3 scripts/test_install.py`、`python3 scripts/test_delivery_next.py` 和 Skill 格式校验。
4. 提交并按项目发布流程创建 tag。

不要为 Codex 和 Claude Code 复制两份 `SKILL.md`；如需调整流程，只修改仓库根目录的主文件。
