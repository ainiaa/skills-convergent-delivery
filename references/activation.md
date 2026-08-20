# 激活与触发

## 使用方式

最可靠的方式是显式说“使用 `$converge` 实现/修复/重构这个任务”。自然语言中的“按方案修改”、“修复已知问题”、“实现后验证”也应命中。

只要计划使用 `$converge-plan`；只读检查使用 `$converge-review`；有限多 Batch 计划使用 `$converge-batch`；只要方案、解释或状态时不启动写入流程。

## 可选 AGENTS.md 片段

若宿主的 Skill 自动发现不稳定，团队可手工加入：

```md
对任何需要修改代码的单个功能、Bug 修复或重构任务，默认使用 `$converge`；
复杂任务实现前使用 `$converge-plan` 拆成有限、可验证短任务；只读检查使用
`$converge-review`；已有有限 Batch 计划的连续调度使用 `$converge-batch`。
```

安装和升级脚本不自动修改 `AGENTS.md`、全局指令或项目配置，避免在用户不知情时改变所有任务的行为。
