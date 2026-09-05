# 原生同步失败降级修复计划

范围：上轮已复现的两处缺口。保留基线已有未提交修改；按 T1 → T2 → T3 同会话执行。原生计划工具未暴露，使用明确标注的文字进度。

1. T1：持久状态支持有据的 native → text 降级；清除原生确认，保持业务事实，恢复继续；先测试再实现。
2. T2：轨迹验收沿用已声明的调用失败；后续无需重复原生调用；首次跳过工具、未告知降级仍拒绝。
3. T3：同步状态契约、执行说明、changelog，执行完整回归和计划审计。

## 机制依据与取舍

沿用上一轮 Skills.sh 发现及原始来源核实结果，不重复全量加载。

| 来源 | 采用 / 不采用与原因 | 行为验证 |
| --- | --- | --- |
| [GitHub harness-engineering](https://github.com/github/awesome-copilot/blob/main/skills/harness-engineering/SKILL.md) | 采用既有 helper 加失败链路回归；不增加框架或平行状态 | 持久写入→重载→下一业务动作 |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/scripts/run_eval.py) | 采用实际调用及引用区别于模型自述；本轮不启动真实模型 | 失败引用、缺失证据、首次跳过工具 |
| [HumanLayer control loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 采用可检查的单步转换，复用 host_sync；不增加显示重试循环 | 独立 revision、恢复不回到 sync-plan |

控制器仍拥有降级决定与写入权；既有 writer lease 和 revision 检查生效。fallback 引用为 controller_attested，不能伪称宿主签名或 UI 渲染证明。简单 inline 任务不增加运行文件或步骤。异常时不重复原生同步；业务失败/停止继续遵循原有门禁。真实宿主 UI、locked differential 和多样本模型行为未覆盖，本轮只交付确定性局部修复。
