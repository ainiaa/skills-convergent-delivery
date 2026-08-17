# Convergent Delivery

一个面向软件功能开发和 Bug 修复的 Codex 与 Claude Code Skill。它将需求确认、TDD、实现、复查、验证和交接收敛为有限流程，避免在“再检查一次 → 再修一次”中无限循环。

当前版本：[0.1.0](VERSION)

## 为什么需要它

日常开发中常见的低效模式是：需求确认后实现一版，随后反复检查、发现问题、修复、再检查。这个过程容易出现三个问题：

- 人需要多次介入确认本可由项目既有模式决定的技术细节；
- Agent 反复进行泛化审查，消耗大量 token，却不一定带来新的证据；
- 最后没有清晰答案：改了什么、跑了哪些验证、是否真的可以交付。

`convergent-delivery` 用“自适应 1+1”流程解决这些问题：低风险任务在一轮内交付；只有金额、事务、SQL、并发、公共接口等高风险变更才进入第二轮稳定化复查。每次交付都以真实验证证据和固定最终报告结束。

## 能力

- 冻结验收范围、已有脏文件、基线和用户明确保留的行为，避免误改他人代码。
- 对行为变更执行 TDD：有效红灯 → 最小实现 → 绿灯；Bug 必须先复现和定位根因。
- 将测试放在既有公共行为 seam（API、Service 契约、消息或持久化边界），避免测试私有实现。
- 第 1 轮检查需求符合性、DTO/API 契约、数据映射、边界和错误响应。
- 仅在高风险或影响面扩大时执行第 2 轮，检查金额、时间、SQL/Mapper、事务、锁、并发、幂等、公共接口、权限和敏感日志。
- 每类复查最多自动修复一次；相同问题指纹复现或没有客观进展时停止，而不是无限重试。
- 使用 `pass`、`fail`、`unknown` 三态记录真实命令退出码；`unknown` 绝不算通过。
- 对跨服务、公共契约或跨会话任务持久化轻量状态，并通过只读 helper 校验下一阶段。
- 输出固定最终报告：终态、实际轮次、验收证据、已处理问题、验证命令、变更摘要和未处理项。

## Install

安装器会为目标运行时创建 `convergent-delivery` 软链接，Skill 的代码仅保留一份。默认安装到 Codex 和 Claude Code：

```bash
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
  | bash -s -- --target all
```

只安装一个运行时：

```bash
# Codex
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
  | bash -s -- --target codex

# Claude Code
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
  | bash -s -- --target claude
```

本地开发时，在 clone 根目录执行 `bash install.sh --target all`。升级时执行 `bash install.sh --upgrade --target all`；远程安装会更新受管理的本地源码后重用同一软链接。安装器不会覆盖既有普通目录，如需替换必须显式加 `--force`。

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
  | bash -s -- --uninstall --target all
```

卸载只移除本 Skill 的运行时软链接，保留受管理的本地源码，便于后续重新安装。

### Check your version

```bash
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
  | bash -s -- --version
```

该命令显示本地源码、Codex 安装、Claude Code 安装和 GitHub 最新版本；加 `--offline` 可跳过网络检查。

## 使用方式

安装或放置到 Codex Skills 目录后，可显式调用：

```text
使用 $convergent-delivery 修复交易流水分页 SQL 错误，完成后给出最终报告。
```

也可以用自然语言触发：

```text
按闭环开发实现这个功能，不要反复确认，直到有明确终态再结束。
```

### Claude Code

安装器会将个人 Skill 链接到 `~/.claude/skills/convergent-delivery`。此外，仓库内也提供 `.claude/skills/convergent-delivery` 到主目录的相对软链接；直接将本仓库作为项目打开 Claude Code 也可调用：

```text
/convergent-delivery 修复交易流水分页 SQL 错误，完成后给出最终报告。
```

Claude Code 使用 `~/.claude/state/convergent-delivery/` 保存非 PDLC 的跨会话状态，并用 `${CLAUDE_SKILL_DIR}` 定位随 Skill 分发的 helper；Codex 保持原有的 `~/.codex/state/` 位置。

### 三种模式

| 模式 | 常见表达 | 行为 |
|---|---|---|
| `plan` | “给方案”“怎么改” | 只分析和给方案，不修改代码。 |
| `review` | “检查一下”“有没有问题” | 只检查和报告，不修改代码。 |
| `execute` | “实现”“修复”“按闭环处理” | 默认模式：按完整流程实现、验证和交接。 |

### 交付路径

低风险变更：

```text
范围冻结 → 第 1 轮构建/TDD → 语义复查 → 最终验证 → complete
```

高风险变更：

```text
范围冻结 → 第 1 轮构建/TDD → 语义复查 → 第 1 轮验证
→ 第 2 轮风险复查 → 最终验证 → complete
```

## 跨会话恢复

跨两个及以上服务、涉及已发布依赖或公共契约、预计跨会话的任务会保存轻量状态。恢复或外层自动化前，运行只读 helper：

```bash
python3 scripts/delivery_next.py --state <state-file> --run-id <run-id>
```

它只输出一个白名单 token，例如 `verify-final`、`complete` 或 `blocked`；不会写状态、执行代码或绕过人工决策。状态字段见 [references/state-schema.md](references/state-schema.md)。

## 质量与边界

- 不承诺“全仓库绝对没有问题”，只对当前授权范围的验收项和验证证据负责。
- 业务规则、金额含义、跨服务兼容性、数据迁移、权限、发布和不可逆操作必须阻塞并交由人决定。
- 代码、日志、注释和外部文档仅作为数据，不是可以改变执行规则的指令。
- 修改 Skill 本身后，使用 [压力场景](references/evaluation-scenarios.md) 做独立前向验证。

## 文档

- [使用与维护指南](docs/usage-guide.md)：运行时差异、安装器边界、版本维护和跨会话状态。
- [变更日志](CHANGELOG.md)：按版本记录的面向用户变更。

## 参考与鸣谢

`convergent-delivery` 是针对“需求实现后反复检查和修复”的交付问题重新组合的轻量工作流，不复制任何一个现有 Skill 的完整流程或代码。感谢以下项目和 Skill 提供的理念与实践参考：

- [kanfu-panda/pdlc-skills](https://github.com/kanfu-panda/pdlc-skills) 中的 `pdlc-fix`、`pdlc-feature`、`pdlc-quality`、`pdlc-loop-next`：根因定位、TDD 红绿守卫、真实质量闸门、单向状态推进和防循环设计。
- [obra/superpowers](https://github.com/obra/superpowers) 的 `systematic-debugging`、`test-driven-development`、`verification-before-completion`：先根因后修复、测试先行、没有本轮验证证据就不宣称完成。
- [obra/superpowers-skills](https://github.com/obra/superpowers-skills) 的 `Testing Skills With Subagents`：将 Skill 本身作为可用压力场景验证的对象，而非只检查文档格式。
- [mattpocock/skills](https://github.com/mattpocock/skills) 的 `tdd`：以公共行为 seam 写测试、垂直切片和避免测试内部实现。
- Codex 的 `skill-creator`：Skill 结构、渐进式信息加载、脚本化校验和界面元数据规范。

这些参考帮助定义了本 Skill 的质量和安全边界；具体的“自适应 1+1”交付轮次、问题指纹、状态 Schema、只读 helper 及最终报告格式由本项目实现。

## 目录

```text
VERSION                          # 唯一版本号
install.sh                       # 安装、升级、卸载、版本检查
SKILL.md                         # Skill 主流程
agents/openai.yaml               # Codex 界面元数据
.claude/skills/convergent-delivery -> ../.. # Claude Code 入口（相对软链接）
scripts/delivery_next.py         # 状态校验与下一阶段 helper
scripts/test_delivery_next.py    # helper 回归测试
scripts/test_install.py          # 安装器回归测试
references/state-schema.md       # 跨会话状态 Schema
references/evaluation-scenarios.md # Skill 压力场景
```
