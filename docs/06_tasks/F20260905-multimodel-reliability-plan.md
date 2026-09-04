# 多模型受控可用性计划

## 冻结范围

目标是让现有多模型 runner 达到“稳定、可控、能给真实项目提效”：真实 CLI 可显式 smoke、receipt 能区分模型/用量可信度、评测覆盖真实 Git 任务，以及本地可执行预算。范围不包括父子任务自动汇总；该能力依赖宿主提供创建、查询、终止和读取完成回执的完整 lifecycle API。

## 决策与参考

| 参考 | 决定 | 原因 | 行为验证 |
|---|---|---|---|
| OpenAI Agents SDK manager orchestration | 采用单一 controller 与受限 specialist | 保持单写入者和统一授权 | 只允许一个 implementer；只读结果不能放行 |
| LangGraph durable execution / interrupt | 采用幂等的外部副作用与显式 pause 语义 | 恢复可从节点开头重跑，未知 launch 不能自动重派 | launch 已落盘但无 receipt 时 blocked |
| Temporal durable workflows | 暂不采用 | 需要新服务、worker 与持久化基础设施，超出本轮最小范围 | 不新增第二状态真源或后台中间件 |
| AutoGen team runtime | 暂不采用 | team transcript state 与本项目不保存完整 prompt/transcript 的边界不一致 | receipt 不保存原始 prompt 或模型回答 |

## 有限任务

1. 将 runner receipt 升级为兼容的可信度结构：模型为 `requested|observed|unavailable`，usage 只在 provider 回执可验证时标为 `observed`。
2. 新增显式 live smoke：在临时 detached worktree 中运行一个只读真实 CLI 角色，输出脱敏 receipt，并始终清理临时 worktree。
3. 新增冻结的真实 Git 任务评测：对同一任务分别运行单模型与多模型 profile，由独立、冻结 evaluator 比较测试结果、范围与受控指标；默认只计划，显式执行才调用 runner。
4. 将预算结果统一写入 receipt/report：时间、输出与调用次数本地强制；没有可信 provider usage 时不推断 token 成本。

## 验收

- 默认命令不启动 CLI、不访问网络、不修改业务 worktree。
- 实际执行必须显式 `--allow-execute`；read-only runner 不能获得写权限。
- 临时 worktree 在成功、失败和超时后均被移除。
- 旧 receipt 仍能读取；新 receipt 的可信度字段纳入 fingerprint。
- 评测报告不保存 prompt、原始模型输出、密钥或成本估算。
- `bash scripts/check.sh --full` 通过。
