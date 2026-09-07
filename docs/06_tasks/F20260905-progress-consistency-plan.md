# 分步进度一致性修复计划

本轮只修审查确认的三处问题，保留已有未提交改动。同会话按 T1 → T2 → T3 → T4 顺序执行；实际进度从验证回执派生，冻结计划不充当可写状态。当前无原生计划工具，明确使用文字进度。

1. T1：覆盖全部合法阶段；blocked 投影停止显示进行中，保留停止动作及一次终态展示。
2. T2：轨迹读取既有持久降级证据；工具重连、恢复后保持文字，不把无依据跳过工具放行。
3. T3：原生调用引用绑定观测的完整步骤投影；拒绝同一引用的矛盾投影或不匹配状态，允许一次真实调用同时完成前步并启动后步。
4. T4：同步状态说明与 changelog，使用 evidence runner 一次执行完整回归并生成回执，完成 Plan v6 审计。

前三步先复现再实现。验证范围冻结为步骤状态、停止、恢复和调用关联；本轮不增加 agent、MCP server、持久显示状态或后台重试，不提交或发布。真实宿主 UI 和独立多样本评估保持 uncovered。

## 依据与取舍

沿用上轮 Skills.sh 发现与原始源码核对结果。

| 来源 | 采用 / 不采用与原因 | 行为验证 |
| --- | --- | --- |
| [HumanLayer](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 采用规则单一来源，控制器只作下一动作；不引入显示重试循环 | blocked 永远保持停止，合法阶段不回到 scope |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/scripts/run_eval.py) | 采用调用观测与输入关联；本轮不启动真实模型 | 错误回执、缺投影、合法合并更新 |
| [GitHub harness-engineering](https://github.com/github/awesome-copilot/blob/main/skills/harness-engineering/SKILL.md) | 采用现有 helper 和行为回归；不另建 harness | 同一持久降级输入贯通状态与轨迹，统一证据执行入口 |

写权和停止责任仍归 controller；投影只读派生，轨迹只读校验，引用真实性由观测者核对。普通 inline 不新增持久文件。能力缺失或失败以文字报告，不以重试或改变判定器获得通过。
