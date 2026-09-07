# 激活与触发

## 使用方式

最可靠的方式是显式说“使用 `$converge` 实现/修复/重构这个任务”。自然语言中的“按方案修改”、“修复已知问题”、“实现后验证”也应命中。

只要计划使用 `$converge-plan`；独立的只读检查使用 `$converge-review`；已有有限跨会话计划使用 `$converge-batch`。只要方案、解释或状态时不启动写入流程。

## 同一会话的持续授权

持续中的写入任务保留已冻结的写入范围。审查请求是只读检查点：审查过程中不修改；返回 finding 后，控制器自动修复同范围问题并验证。用户明确“仅审查”“不要修改”、停止或取消时才暂停写入；范围外 finding 只记录影响并请求一个必要决定。

独立的 `$converge-review` 始终只读。它不会自行恢复写入；只有根控制器在已有持续写入任务中把审查作为检查点时，才按原授权继续。跨独立会话不推断旧授权，使用显式 resume/capsule 或重新授权。

## 可选 AGENTS.md 片段

若宿主的 Skill 自动发现不稳定，团队可手工加入：

```md
对任何需要修改代码的单个功能、Bug 修复或重构任务，默认使用 `$converge`。
同一会话内持续已授权的写入任务应自动修复同范围 finding；仅审查请求使用
`$converge-review`，复杂任务先使用 `$converge-plan`，已有有限跨会话计划使用
`$converge-batch`。
```

安装和升级脚本不自动修改 `AGENTS.md`、全局指令或项目配置，避免在用户不知情时改变所有任务的行为。

## 诊断

隐式触发最终由宿主决定，Skill 无法强制。未触发时先显式使用 `$converge`，再运行 `bash "$CONVERGE_SKILL_DIR/install.sh" --doctor --target codex --offline` 检查入口、版本、必需 Provider manifest 和本地解析结果；不要通过安装器自动改写项目或全局 `AGENTS.md`。
