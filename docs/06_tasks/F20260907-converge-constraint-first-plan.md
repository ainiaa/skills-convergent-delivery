<!-- PDLC-TRACE -->
<!-- 功能ID: F20260907-constraint-first-converge -->
<!-- 功能名称: converge-constraint-first -->
<!-- 阶段: plan -->
<!-- 创建时间: 2026-09-07 -->

# Converge Constraint-First 改造计划

作者：Jeff.Liu

## 目标

让 Converge 在**同一会话的已授权写入任务**中持续推进：少问无关问题；审查发现同范围问题后自动闭环；没有本轮验证不得称完成。

本计划不承诺跨独立会话自动恢复，不把本地状态或脚本夹具描述为真实宿主自动控制。

## 已决边界

1. 当前会话的写入授权持续有效，直到用户明确停止、要求“仅审查/不要修改”，或提出范围外目标。
2. 持续写入任务中的审查是只读检查点；报告完成后，属于冻结范围、验收项或本轮改动影响面的 finding 自动进入修复。
3. 范围外 finding 只登记，并一次提出需要的业务或兼容性决定；不得借审查扩大写入范围。
4. 不新增 agent、后台循环、运行时状态或真实宿主 bridge。既有自治扩展不删除，但不作为根入口能力承诺。
5. 本地测试只验证确定性规则；真实行为结论必须来自后续 fresh Codex 会话 smoke，缺失时保持 `uncovered`。

## 执行任务

| 顺序 | 结果 | 受控文件 | 验收 |
|---|---|---|---|
| T1 | 冻结八个交互行为场景与可校验结构 | `evals/converge-interaction-v1.json`、`scripts/test_interaction_contract.py`、`scripts/check.sh` | 场景覆盖写入、仅审查、审查后闭环、范围外、决策、停止、简单与复杂任务；校验器拒绝缺项和矛盾规则。 |
| T2 | 根入口只保留每轮关键约束 | `SKILL.md`、`scripts/test_skill_contracts.py` | 根入口说明持续授权、最少提问、finding 三分法、真实验证和按需加载；不再承诺不存在的宿主生命周期。 |
| T3 | 对齐触发、路由和执行 reference | `references/activation.md`、`references/task-routing.md`、`references/execution-protocol.md` 及其定向测试 | 审查不再无条件清空同一会话授权；简单路径不加载复杂协议；in-scope finding 自动闭环。 |
| T4 | 对齐交付口径与用户可见说明 | `references/reporting.md`、`README.md`、`CHANGELOG.md` | `check.sh --full` 仅称确定性回归；宿主行为和成本没有 smoke 证据时明确 `uncovered`。 |
| T5 | 执行确定性回归和最小复核 | 所有改动文件 | 新增测试先红后绿；定向测试、`bash scripts/check.sh --full`、`git diff --check` 通过。 |
| T6 | 交付 fresh-host smoke 清单 | `evals/converge-interaction-v1.json` | 生成可由独立 fresh Codex 任务运行的 8 场景清单和记录字段；不在本轮伪造 live 结果。 |

## 交互场景

1. 局部 bug 修复：直接开始、先失败后修复、验证后结束。
2. 已授权修复中的审查：审查只读，随后自动修复同范围 finding。
3. 用户明确“仅审查”：不写入，也不恢复写入。
4. 范围外 finding：记录影响并只提出一个决策，不擅自修复。
5. 已有决定：不重复提问。
6. 不可逆/公共兼容选择：停止并给出推荐。
7. 简单任务：不读取或宣称 worker、自治、全量收口。
8. 复杂任务：先给有限计划，按切片执行，不新增无关代理。

## 不做的内容

- 不重写或删除既有 Single State、自治、Capsule 或多模型实现。
- 不增加新的评估服务、模型 judge、外部依赖、CI workflow 或可写 backlog。
- 不以文字匹配测试证明模型行为；场景文件只冻结期望，真实行为另以 fresh-host smoke 验收。

## 完成判定

T1–T5 的确定性验证通过，且 T6 可被独立执行。最终报告明确区分“确定性回归通过”和“真实宿主 smoke 未执行/已执行”的范围。
