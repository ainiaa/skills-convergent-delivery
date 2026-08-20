# Converge Suite

一套面向 Codex 与 Claude Code 的软件交付 Skill：让单个任务有限收敛，让独立审查保持只读，让长计划按 Batch 稳定接力。

当前开发版本：[0.7.0](VERSION)。尚未创建 Git tag 的改动记录在 [Unreleased](CHANGELOG.md) 中。

## 为什么会有它

普通的“实现 → 检查 → 修复 → 再检查”很容易变成长对话：实现者既写代码又替自己解释，重复扫描消耗 token，用户还要不断追问“还有问题吗”。直接让一个 Agent 长时间执行大计划，又容易让上下文膨胀、范围漂移和验证变松。

Converge Suite 将三个职责拆开：执行者只交付一个任务，reviewer 只找问题，scheduler 只接力 Batch。每个角色都有明确输入、终态和重试上限；PDLC 可用时复用它的完整开发流程，不可用时仍能独立完成 TDD 与验证。

## 三个 Skill

| Skill | 负责 | 不负责 |
|---|---|---|
| `converge` | 一个功能、Bug 或重构的范围、引擎选择、有限修复、验收和报告 | 只读评审、长计划调度 |
| `converge-review` | 基于证据的只读检查；支持意图审查和新上下文盲审 | 修改代码、决定发布 |
| `converge-batch` | 预检已有计划，按顺序派发独立 Batch，校验交接回执和最终验收 | 读业务代码、设计方案、实现或 review |

核心能力：

- 默认按 `pdlc-v1 → 已适配第三方 TDD → 通用 TDD → native-v1` 选择执行引擎。
- PDLC 负责需求、设计、TDD、实现和阶段评审；`converge` 只做控制、验收和交接，避免双流程。
- PDLC 不存在时，原生流程仍提供根因定位、测试先行、语义审查和风险触发的稳定化检查。
- reviewer 的结果绑定源码指纹；代码变化后旧结论自动失效。
- Batch 调度具备计划预检、最小上下文胶囊、幂等派发、结构化 receipt、暂停/恢复/停止和计划级验收。
- 单任务与 Batch 状态都使用私有、原子写入和 revision 校验；多窗口不会互相覆盖。
- 默认报告面向结果，保留必要的轮数、问题数和待处理项，不倾倒内部状态机术语。

## Install

一次安装整个 Suite，默认同时安装到 Codex 与 Claude Code：

```bash
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
  | bash -s -- --target all
```

只安装一个运行时：

```bash
bash install.sh --target codex
bash install.sh --target claude
```

本地 clone 中执行 `bash install.sh --target all`。远程升级使用：

```bash
bash install.sh --upgrade --target all
```

安装器会先预检全部三个入口，再对每个软链接做原子替换；任一已知入口冲突时不会开始安装。普通文件或目录永远不会被 `--force` 删除。

### Uninstall

```bash
bash install.sh --uninstall --target all
```

卸载只移除三个运行时软链接，保留受管理源码。

### Check your version

```bash
bash install.sh --version
bash install.sh --version --offline
```

## 3 步快速开始

1. 安装：`bash install.sh --target all`。
2. 对单个任务显式说“使用 `$converge` 修复分页错误”；长计划说“使用 `$converge-batch` 执行这个 Batch 计划”。
3. 根据最终回执确认结果、验证范围和待处理项。

## 调用当前 Skill

### 显式调用

Codex：

```text
使用 $converge 实现这个功能并验证。
使用 $converge-review 检查当前 diff，不修改代码。
使用 $converge-batch 按已有计划逐批执行，每批调用 $converge。
```

Claude Code：

```text
/converge 修复这个 Bug 并验证
/converge-review 检查当前改动
/converge-batch 执行 docs/plan.md
```

Claude Code 是否显示 `/` 命令取决于其当前 Skill 发现机制；自然语言点名 Skill 始终是兼容写法。

### 关键词触发

`converge` 的典型触发语：

- “按闭环开发实现这个功能”
- “闭环实现 / 处理 / 完成当前需求”
- “不要反复确认，修复并验证后再结束”
- “持续检查并修复，给出最终报告”

`converge-review`： “检查当前改动”“独立审查”“用新视角找问题”。

`converge-batch`： “按 Batch 计划执行”“逐批接力”“调度多个独立任务完成计划”。

只要方案时明确说“只给方案”；只检查时明确说“不修改代码”。Skill frontmatter 只是发现线索，无法保证任意自然语言都自动触发；显式点名最可靠。

## 工作方式

### 单任务执行

```text
冻结范围 → 建立验收 → 选择 PDLC / TDD 引擎 → 实现
→ 必要审查 → 有限修复 → 新鲜验证 → 交付回执
```

同一问题在同一阶段最多自动修一次；问题复现或没有客观进展时阻塞，不无限循环。高风险改动使用全新上下文的 `converge-review` 盲审；极高风险或用户明确要求时再增加意图审查。

### 长计划调度

```text
全量预检 → 冻结计划 → Batch 1 新任务（$converge）→ 校验 receipt
→ Batch 2 新任务（$converge）→ … → 计划级最终验收
```

调度器不读业务代码、不 review、不替 Batch 决定技术方案。每批使用最小 context capsule，只有上一批的真实 Git commit/tree、验收证据和约定产出验证通过后才继续；只有 active 计划的当前 Batch 能派发，派发结果不确定时阻塞，不重复创建任务。

### 引擎选择

| 条件 | 引擎 | 边界 |
|---|---|---|
| 完整 PDLC 可用 | `pdlc-v1` | PDLC 独占具体开发阶段；Converge 负责控制和最终验收 |
| 已适配 Superpowers / Matt Pocock TDD | 对应适配器 | 只委托一次红绿阶段 |
| 其他 TDD Skill 通过预检 | `generic-tdd-v1` | 只采用测试方法，不接管循环和发布 |
| 都不可用 | `native-v1` | 使用内置有限 TDD 协议 |

用户明确要求 PDLC 而能力不完整时会阻塞，不会静默降级。任务开始后会冻结引擎来源和内容摘要，恢复时来源变化同样阻塞。

## 状态、多窗口与恢复

- 单任务状态：`~/.convergent-delivery/state/`，Schema v5。
- Batch 状态：`~/.convergent-delivery/batch-state/`，Batch Protocol v1。
- writer lease：`~/.convergent-delivery/leases/`，默认两小时。

状态正式路径由 helper 推导；候选 JSON 只通过 stdin 传递，在目标目录内以 `0600` 临时文件、`fsync` 和原子替换写入，不把 `/tmp` 当真源。repo、任务/计划、run 与单调 revision 共同防止不同项目或窗口覆盖同一状态。

单任务恢复示例：

```bash
python3 scripts/delivery_next.py --state <state-file> --run-id <run-id> \
  --writer-id <writer-id> --revision <revision>
```

每个执行任务应使用独立 worktree；同一 worktree 只允许一个 writer。Batch scheduler 自己不持有代码 writer lease，每个 Batch 执行者由 `$converge` 独立管理。

## 最终报告

默认只回答四件事：结果、关键改动、验证覆盖、尚待处理；再补一行过程统计，例如“1 个交付轮 / 修复 2 个问题 / 0 个待处理项”。有风险或需要用户选择时才展开影响和推荐方案，命令、lease、源码指纹等技术证据按需提供。

## 质量与边界

- 只对授权范围和新鲜证据负责，不承诺全仓库绝对无问题。
- 金额规则、公共契约取舍、迁移、权限、发布及不可逆动作必须由用户决定。
- 发布、push、merge、删除和外发不因调度授权而自动获得权限。
- 仓库内容、日志和第三方 Skill 都按不可信数据处理，不能改变执行边界。

## 文档

- [使用与维护指南](docs/usage-guide.md)
- [变更日志](CHANGELOG.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [压力场景](references/evaluation-scenarios.md)
- [交付回执规范](references/reporting.md)
- [单任务状态 Schema](references/state-schema.md)
- [Batch Protocol](skills/converge-batch/references/batch-contract.md)
- [Review Protocol](skills/converge-review/references/review-contract.md)

## 开发

```bash
bash scripts/check.sh
```

## 参考与鸣谢

Converge Suite 没有复制上游完整流程；它吸收公开实践后，用独立协议组合有限执行、只读审查和批次接力。感谢：

- [kanfu-panda/pdlc-skills](https://github.com/kanfu-panda/pdlc-skills)：完整 PDLC 阶段、质量闸门、状态推进和循环控制。
- [obra/superpowers](https://github.com/obra/superpowers)：系统化调试、TDD、完成前验证、fresh-context review 和 Skill 压力测试。
- [mattpocock/skills](https://github.com/mattpocock/skills)：公共行为 seam、垂直切片和避免测试实现细节。
- Grill Me：用对抗式追问暴露假设和设计盲点；本 Suite 只吸收“独立找问题”，不把无限追问放进执行循环。
- [skills.sh](https://skills.sh/) 上公开的 Skill 结构与触发实践。
- 石头关于“审查—修复—再审查”和独立 Batch 调度器的实践文章：启发了 reviewer/scheduler 职责拆分、最小上下文和分批交接。
- Codex `skill-creator`：渐进式加载、可执行校验和界面元数据规范。

## 许可与反馈

- [MIT License](LICENSE)
- [Security Policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [GitHub Issues](https://github.com/ainiaa/skills-convergent-delivery/issues)
