# Runner 边界与分步验收修复计划

作者：Jeff.Liu

基线：`601ac9284750ffe5de25f0c0baadd09eaeb84958`；工作区初始干净。同会话顺序执行，不提交、不安装、不调用真实模型。机器计划以同名 JSON 为准；进度由实际验证回执派生。

## T1

输出读取或进度回调失败时，两个本地 runner 均返回 unknown 并清场，不交付部分成功结果。

验证：`PYTHONPATH=scripts python3 -m unittest test_codex_exec_runner test_claude_exec_runner`。

## T2

本地 runner 显式禁止原生子代理派发，保留实施和只读验证所需工具。

验证：`PYTHONPATH=scripts python3 -m unittest test_codex_exec_runner test_claude_exec_runner test_runner_launch test_runner_lifecycle`。

## T3

分步轨迹验收可拒绝先修改后汇报、失败后推进和恢复重做，并明确证据来源及未覆盖范围。

验证：`PYTHONPATH=scripts python3 -m unittest test_step_trace_eval`。

## T4

文档和变更日志准确反映修复及证据边界，现有功能通过全量回归。

验证：`CONVERGE_QUICK_VALIDATE=/tmp/converge-official-quick-validate.py bash scripts/check.sh --full`。

## 参考取舍

- 采用 Anthropic [skill-creator 的事件观测](https://github.com/anthropics/skills/blob/main/skills/skill-creator/scripts/run_eval.py)：检查有序行为记录，测试正常、异常、恢复与缺失证据；不以关键词出现代表执行成功。
- 采用 [宿主原生子代理限制](https://learn.chatgpt.com/docs/agent-configuration/subagents)；通过启动命令和本机只读配置探测验证，不新增代理树。
- 采用 [harness-engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/harness-engineering/SKILL.md) 的冻结对照和证据分级；不新增状态机、监控代理或自进化循环。
- [MCP 工具允许列表](https://learn.chatgpt.com/docs/config-file/config-reference) 暂不采用：未经需求映射整体禁用可能损失必要能力，不在两项实现缺陷中夹带权限重构。

## 验收边界

旧 Controller Snapshot 已保存在候选仓库外。保持旧 judge/catalog/evaluator 不变。T3 的轨迹为 evaluator-attested 输入，不能冒充宿主签名；真实多样本行为及 locked host differential 缺少能力时保留 uncovered。测试不要求额外运行时状态，也不改变普通简单任务路径。
