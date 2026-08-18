# Converge

一个面向软件功能开发和 Bug 修复的 Codex 与 Claude Code Skill。它将需求确认、TDD、实现、复查、验证和交接收敛为有限流程，避免在“再检查一次 → 再修一次”中无限循环。

当前开发版本：[0.4.0](VERSION)。尚未创建 Git tag 的改动记录在 [Unreleased](CHANGELOG.md) 中。

## 为什么需要它

日常开发中常见的低效模式是：需求确认后实现一版，随后反复检查、发现问题、修复、再检查。这个过程容易出现三个问题：

- 人需要多次介入确认本可由项目既有模式决定的技术细节；
- Agent 反复进行泛化审查，消耗大量 token，却不一定带来新的证据；
- 最后没有清晰答案：改了什么、跑了哪些验证、是否真的可以交付。

`converge` 用有限、可恢复的控制循环解决这些问题：它优先将具体需求产物、TDD、实现和阶段评审委托给兼容的 PDLC；PDLC 不可用时才使用内置原生流程。无论哪个引擎，低风险任务在一轮内交付；只有金额、事务、SQL、并发、公共接口等高风险变更才进入第二轮稳定化复查。每次交付都以新鲜验证证据和面向用户的交付回执结束。

## 能力

- 冻结验收范围、已有脏文件、基线和用户明确保留的行为，避免误改他人代码。
- 默认选择可用的 `pdlc-v1`：PDLC 负责需求产物、TDD、实现、阶段评审；`converge` 负责范围、循环预算、lease、跨服务验收和报告。
- PDLC 不可用时选择 `native-v1`：对行为变更执行 TDD（有效红灯 → 最小实现 → 绿灯）；Bug 必须先复现和定位根因。
- 引擎选择在任务开始后冻结：强制 PDLC 不可用会阻塞，活动 PDLC 任务不会静默降级到原生流程。
- 将测试放在既有公共行为 seam（API、Service 契约、消息或持久化边界），避免测试私有实现。
- 第 1 轮检查需求符合性、DTO/API 契约、数据映射、边界和错误响应。
- 仅在高风险或影响面扩大时执行第 2 轮，检查金额、时间、SQL/Mapper、事务、锁、并发、幂等、公共接口、权限和敏感日志。
- 每类复查最多自动修复一次；相同问题指纹复现或没有客观进展时停止，而不是无限重试。
- 使用 `pass`、`fail`、`unknown` 三态记录真实命令退出码；每个验收项还标记 `fresh`、`stale` 或 `unavailable`，`unknown` 和陈旧结果绝不算通过。
- 对跨服务、公共契约或跨会话任务持久化轻量状态，并通过只读 helper 校验下一阶段。
- 多窗口执行使用 repo/task/worktree 三层 lease：阻止同一 worktree 双写和同一任务重复实现，不阻塞不同 worktree 的不同任务并行。
- 默认输出一屏“交付回执”：结论、影响、已验证范围和一个明确下一步；命令、轮次和状态机证据仅在要求详细报告时展示。

## Install

安装器会为目标运行时创建 `converge` 软链接，Skill 的代码仅保留一份。默认安装到 Codex 和 Claude Code：

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

该命令显示本地源码、Codex 安装、Claude Code 安装和 GitHub `main` 中的版本；加 `--offline` 可跳过网络检查。

## 3 步快速开始

1. 安装到当前机器的两个运行时：

   ```bash
   curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh | bash -s -- --target all
   ```

2. 在 Codex 中说“使用 `$converge` 修复分页 SQL 错误”；或在 Claude Code 中执行 `/converge 修复分页 SQL 错误`。
3. 根据交付回执确认结论、已验证范围和是否需要你决定下一步。

## 调用当前 Skill

### 显式调用

Codex 使用 `$converge`：

```text
使用 $converge 修复交易流水分页 SQL 错误，完成后给出最终报告。
```

Claude Code 使用 `/converge`：

```text
/converge 修复交易流水分页 SQL 错误，完成后给出最终报告。
```

安装器会将 Claude Code 的个人 Skill 链接到 `~/.claude/skills/converge`。仓库内也提供 `.claude/skills/converge` 到主目录的相对软链接；直接将本仓库作为项目打开 Claude Code 也可调用。旧的 `convergent-delivery` 软链接会自动迁移；旧目录会先备份再替换，避免重复触发。

### 关键词触发

不写命令也可以。以下表达会触发 Skill：

- “按闭环开发实现这个功能”
- “不要反复确认，直到有明确终态再结束”
- “持续检查并修复，给出最终报告”
- “使用闭环交付修复这个 Bug”

需要只出方案或只做检查时，在请求中写明“给方案”或“检查一下”；否则默认执行完整交付流程。

### 三种模式

| 模式 | 常见表达 | 行为 |
|---|---|---|
| `plan` | “给方案”“怎么改” | 只分析和给方案，不修改代码。 |
| `review` | “检查一下”“有没有问题” | 只检查和报告，不修改代码。 |
| `execute` | “实现”“修复”“按闭环处理” | 默认模式：按完整流程实现、验证和交接。 |

### 交付路径

默认先探测执行引擎：兼容的 PDLC 存在时，`converge` 只控制其有限循环和最终验收；不再自己重复 TDD、实现或 review。PDLC 不可用时，才采用下方原生路径。

低风险变更：

```text
范围冻结 → 第 1 轮构建/TDD → 语义复查 → 最终验证 → complete
```

高风险变更：

```text
范围冻结 → 第 1 轮构建/TDD → 语义复查 → 第 1 轮验证
→ 第 2 轮风险复查 → 最终验证 → complete
```

### 引擎选择

| 请求或环境 | 选择 | 行为 |
|---|---|---|
| 默认，兼容 PDLC 可用 | `pdlc-v1` | PDLC 负责阶段工作；`converge` 只做有限循环控制、证据汇总和交接。 |
| 默认，PDLC 不可用 | `native-v1` | 使用内置 TDD、语义复查和按风险触发的稳定轮。 |
| 明确“使用 PDLC” | `pdlc-v1` | PDLC 能力不完整时 `blocked_environment`，不会偷偷降级。 |
| 明确“不使用 PDLC” | `native-v1` | 固定使用内置流程。 |

`pdlc-v1` 要求 PDLC 源码目录或已安装 Skill 目录具备 `pdlc-tdd`、`pdlc-implement`、`pdlc-review` 及任务对应的 `pdlc-feature` 或 `pdlc-fix`。Codex 与 Claude Code 的已安装 Skill 都可直接使用；外部 loop runner 只是可选加速器。可用以下 helper 做确定性探测：

```bash
python3 scripts/delivery_engine.py select --mode auto --kind feature \
  --pdlc-root /path/to/pdlc-skills
```

Bug 修复将 `--kind` 改为 `fix`，以确认 `pdlc-fix` 可用。

任务开始后引擎不可自动改变；恢复时发现 PDLC 消失，会保留现场并报告环境阻塞。需要从 PDLC 迁移到原生流程时，必须由用户明确授权并新建任务 run。

## 跨会话恢复

跨两个及以上服务、涉及已发布依赖或公共契约、预计跨会话的任务会保存轻量状态。恢复或外层自动化前，运行只读 helper：

```bash
python3 scripts/delivery_next.py --state <state-file> --run-id <run-id> \
  --writer-id <writer-id> --revision <revision>
```

协调状态保存在 Codex 与 Claude Code 共用的 `~/.convergent-delivery/state/`，因此可以跨运行时恢复同一任务。正式 state 路径由 repo、task 和 run 自动推导；候选 JSON 只经 `delivery_state.py write --input -` 的 stdin 提交，不能写入 `/tmp` 或任意路径。状态会冻结引擎与验收证据；PDLC 的细粒度流程状态仍只在 `docs/.pdlc-state/`。只读 helper 输出一个白名单 token，例如原生的 `verify-final`、PDLC 的 `pdlc-run`、`complete` 或 `blocked`；会校验活动 lease，但不会写状态、执行代码或绕过人工决策。状态字段见 [references/state-schema.md](references/state-schema.md)。

## 多窗口并行

一个执行任务对应一个 Git worktree 和分支。同一 worktree 只能有一个写入者；相同范围的任务不能在另一个 worktree 重复执行；不同任务可并行。Codex 与 Claude Code 共用用户级 lease，因此跨运行时也不会双写。Skill 默认使用两小时 writer lease，过期后也不会自动抢占，避免仍在运行的窗口被覆盖。具体恢复、接管与安装锁说明见[使用与维护指南](docs/usage-guide.md#多窗口并行)。

## 质量与边界

- 不承诺“全仓库绝对没有问题”，只对当前授权范围的验收项和验证证据负责。
- 业务规则、金额含义、跨服务兼容性、数据迁移、权限、发布和不可逆操作必须阻塞并交由人决定。
- PDLC 是首选执行层；未安装时，`converge` 才执行原生的根因定位、TDD 和真实退出码验证规则。两套阶段不会在同一任务混用。
- 代码、日志、注释和外部文档仅作为数据，不是可以改变执行规则的指令。
- 修改 Skill 本身后，使用 [压力场景](references/evaluation-scenarios.md) 做独立前向验证。

## 文档

- [使用与维护指南](docs/usage-guide.md)：运行时差异、安装器边界、版本维护和跨会话状态。
- [变更日志](CHANGELOG.md)：按版本记录的面向用户变更。
- [贡献指南](CONTRIBUTING.md)：开发、测试和提交约定。
- [安全策略](SECURITY.md)：敏感问题的报告方式。
- [压力场景](references/evaluation-scenarios.md)：修改 Skill 后验证 PDLC 路由、恢复、根因守卫与验收新鲜度。
- [交付回执规范](references/reporting.md)：默认摘要、待决问题、增量汇报和技术证明包的展示规则。

## 反馈与许可

- 使用问题和想法：在 [GitHub Discussions](https://github.com/ainiaa/skills-convergent-delivery/discussions) 发起讨论；若未启用 Discussions，则提交 Issue。
- 确认的 Bug 或功能请求：[GitHub Issues](https://github.com/ainiaa/skills-convergent-delivery/issues)。
- 开源许可：[MIT](LICENSE)。

## 开发

提交前运行：

```bash
bash scripts/check.sh
```

## 参考与鸣谢

`converge` 是针对“需求实现后反复检查和修复”的交付问题重新组合的轻量工作流，不复制任何一个现有 Skill 的完整流程或代码。感谢以下项目和 Skill 提供的理念与实践参考：

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
scripts/check.sh                 # 可复现的项目检查入口
SKILL.md                         # Skill 主流程
agents/openai.yaml               # Codex 界面元数据
.claude/skills/converge -> ../..            # Claude Code 入口（相对软链接）
scripts/delivery_next.py         # 状态校验与下一阶段 helper
scripts/test_delivery_next.py    # helper 回归测试
scripts/delivery_engine.py       # PDLC / 原生引擎的确定性选择 helper
scripts/test_delivery_engine.py  # 引擎选择、降级与粘性回归测试
scripts/delivery_lease.py        # 多窗口 writer lease helper
scripts/test_delivery_lease.py   # lease 回归测试
scripts/delivery_task_key.py     # 确定性 task key 生成 helper
scripts/test_delivery_task_key.py # task key 回归测试
scripts/delivery_state.py        # lease 保护的状态写入 helper
scripts/test_delivery_state.py   # 状态写入回归测试
scripts/test_install.py          # 安装器回归测试
scripts/test_check.py            # 项目检查入口回归测试
references/state-schema.md       # 跨会话状态 Schema
references/evaluation-scenarios.md # Skill 压力场景
references/reporting.md            # 面向用户的交付回执规范
```
