# Converge Suite

面向 Codex 与 Claude Code 的软件交付 Skill：将复杂需求拆成有限任务，要求新鲜验证与明确交付边界。

当前发布版本：[0.1.0](VERSION)。未发布改动见 [变更日志](CHANGELOG.md) 的 Unreleased。

## 3 步快速开始

1. 安装当前稳定版本：

   ```bash
   curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/v0.1.0/install.sh \
     | bash -s -- --release 0.1.0 --target all
   ```

2. 重启或刷新 Codex / Claude Code 的 Skill 发现；找不到 Skill 时运行 `bash install.sh --doctor --target codex --offline`。

3. 不确定时，先用 `converge`：

   ```text
   使用 $converge 修复登录后跳转错误，运行相关测试并交付结果；不要发布或 push。
   ```

### 选哪个 Skill

| 需求 | Skill |
|---|---|
| 实现功能、修 Bug、重构并验证 | `converge` |
| 只制定可执行计划 | `converge-plan` |
| 只读检查当前改动 | `converge-review` |
| 执行已有跨会话计划 | `converge-batch` |
| 验收 Converge Suite 自身变更 | `converge-eval` |
| 明确要求自治续跑 | `converge-autonomy` |
| 明确要求多模型协作 | `converge-multimodel` |

## 为什么会有它

Converge 让 planner、执行者、reviewer 和调度器各自只承担一类职责：单任务有限收敛，复杂任务先计划后分批执行；所有结论以实际源码和新鲜验证为准。

## 五个核心 Skill 与可选扩展

`converge` 控制单个交付任务；`converge-plan` 只产出计划；`converge-review` 只读；`converge-batch` 执行既有计划；`converge-eval` 验收 Suite 行为。`converge-autonomy` 与 `converge-multimodel` 是显式选择的扩展，不会默认启动。

发布、push、merge、删除及其他外发或不可逆操作始终需要单独授权。完整流程、状态、Provider 和执行控制由各 Skill 与其引用文档维护，README 不重复协议细节。

## 安装与升级

本地 clone 安装：

```bash
bash install.sh --target all
```

升级当前已安装版本：

```bash
bash install.sh --upgrade --target all
```

远程来源三选一，且不能与本地 `--source` 混用：

| 目的 | 选项 |
|---|---|
| 跟随开发分支 | `--latest` |
| 安装正式版本 | `--release <version>` |
| 安装预发布或精确 tag | `--tag <tag>` |

稳定版应使用前述固定 tag bootstrap；只有明确需要开发版本时才传 `--latest`。安装器默认注册七个入口，但不会安装 Hook、启动 service 或运行模型。卸载、单运行时安装、诊断与常见问题见 [使用与维护指南](docs/usage-guide.md)。

## 调用当前 Skill

Codex 使用 `$skill-name`，Claude Code 使用 `/skill-name`；两者都可使用自然语言显式点名：

```text
使用 $converge 实现这个功能并验证。
/converge 修复这个 Bug 并验证
使用 $converge-plan 拆成可验证短任务，不修改代码。
/converge-review 检查当前改动
```

### 关键词触发

显式点名最可靠。典型提示包括“按闭环开发实现这个功能”和“不要反复确认，修复并验证后再结束”。只给方案时写明“不修改代码”；只检查时写明“只读审查”。团队激活方式见 [激活与触发](references/activation.md)。

## 多模型协作

默认不启用。用户明确说“使用多模型配合开发”时，才使用固定角色：Terra medium 路由与取证、Terra high 规格与审查、Luna high 受限实现、Sol high 裁决高风险冲突。它不能替代真实测试或发布授权；完整边界和配置见 [多模型协作](references/multi-model.md)。

```text
使用 $converge-multimodel 配合开发修复支付重试问题；运行相关测试，不要发布。
```

## 自治续跑

仅在用户明确要求闭环续跑时使用 `converge-autonomy`。Stop Hook 与跨会话 service 都需要额外、显式安装；它们的能力边界见 [自治适配](references/runtime-adapters.md)。

## 状态与交付

简单任务不创建正式状态；持久任务使用共享状态、writer lease 和内容寻址快照，以支持有限恢复和单写入者约束。详细字段、恢复命令和多窗口规则见 [单任务状态 Schema](references/state-schema.md)、[执行控制](references/execution-control.md) 与 [使用与维护指南](docs/usage-guide.md)。

native 运行时任务需要可执行的 CodeGraph CLI、目标仓库已有 `.codegraph/` 索引和项目 coverage 配置；执行前运行 `tdd_impact_guard.py preflight --workspace <项目路径>`（脚本位于已安装 Converge 的 `scripts/`）。缺口在写入前报告，安装器不会自动建索引或增加 coverage 依赖。PDLC 使用自身验证配置。

正式 `converge-eval` 当前缺少 evaluator lifecycle bridge，预检会返回 `uncovered`。离线回归和统计测试可运行，但不能声明 locked differential 或真实宿主验收已通过；详见 [Eval 当前能力](skills/converge-eval/SKILL.md)。

最终报告只说明结果、关键改动、验证覆盖与待处理项，并展示工作区累计的 Git 真值；Codex 单步角标不代表任务累计规模。不会把“未发现任何问题”当作全仓库保证。

## 文档

- [使用与维护指南](docs/usage-guide.md)
- [变更日志](CHANGELOG.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [Plan Contract](skills/converge-plan/references/plan-contract.md)
- [执行控制](references/execution-control.md)
- [Review Protocol](skills/converge-review/references/review-contract.md)
- [Evaluation Contract](skills/converge-eval/references/evaluation-contract.json)

## 开发

```bash
# 日常核心校验
bash scripts/check.sh
# 发布前或修改扩展后执行完整校验
bash scripts/check.sh --full
```

## 参考与鸣谢

Converge Suite 没有复制上游完整流程；它吸收公开实践后，用独立协议组合有限执行、只读审查和批次接力。感谢：

- [kanfu-panda/pdlc-skills](https://github.com/kanfu-panda/pdlc-skills)：完整 PDLC 阶段、质量闸门、状态推进和循环控制。
- [obra/superpowers](https://github.com/obra/superpowers)：系统化调试、TDD、完成前验证、fresh-context review 和 Skill 压力测试。
- [obra/external-subagents](https://github.com/obra/external-subagents)：Codex CLI 外部 leaf 的可恢复 launch/receipt 边界；本 Suite 仅采用其“外部 runner 不伪装宿主 worker”的原则，不复制其 state engine。
- [GitHub Spec Kit](https://github.com/github/spec-kit)：Spec → Plan → Tasks → Implement 的追溯结构。
- [gstack](https://github.com/garrytan/gstack)：计划就绪检查、决策记录和 plan-vs-diff 完成审计。
- [mattpocock/skills](https://github.com/mattpocock/skills)：公共行为 seam、垂直切片和避免测试实现细节。
- [grill-with-docs](https://www.skills.sh/mattpocock/skills/grill-with-docs)：逐一追问并结合代码库、领域词汇、`CONTEXT.md` 与 ADR 形成必要决策；本 Suite 只采用“未闭合决策先澄清”的边界，不默认生成文档或 issue。
- Builder.io 的 planning/review Skills 与公开的 delegate/taskflow 实践：启发了高风险计划仲裁、fresh worker、依赖 wave 和结构化交接。
- [skills.sh](https://skills.sh/) 上公开的 Skill 结构与触发实践。
- [石头关于“审查—修复—再审查”和独立 Batch 调度器的实践文章](https://mp.weixin.qq.com/s/Ea8g3uH5f7kPKR0B-39cTg)：启发了 reviewer/scheduler 职责拆分、最小上下文和分批交接。
- Codex `skill-creator`：渐进式加载、可执行校验和界面元数据规范。

## 许可与反馈

[MIT License](LICENSE) · [Security Policy](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [GitHub Issues](https://github.com/ainiaa/skills-convergent-delivery/issues)
