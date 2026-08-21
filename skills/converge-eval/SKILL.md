---
name: converge-eval
description: Evaluate Converge Suite behavior with frozen control/candidate comparisons, fresh multi-sample decisions, and regressions selected from touched control surfaces. Use after changing Converge rules; do not use for implementation, review, or deployment.
---

# Converge Eval：独立行为验收

只负责有限、可复现的行为评估。不得实现候选规则、修改被测工作区、替代 `converge-review` 做代码审查，或直接执行外部副作用。

## 输入与冻结

开始前读取 [机器契约](references/evaluation-contract.json) 和根级 [历史逃逸 catalog](../../references/evaluation-catalog.json)。输入至少包含冻结验收项、`touched_control_surfaces`、control 来源、candidate 来源、允许读取范围和关键决策；缺少任一项时把对应范围记为 `uncovered`，不猜测。

修改 Converge 自身时，在接触 candidate 前把旧版 control 固定为不可变 commit、tree 或隔离快照。control 与 candidate 必须运行相同场景、输入、判定器和样本预算；分别保存原始结果，再计算差分。不能冻结旧版时不得用当前候选冒充对照。

## 场景集合

1. `known_acceptance`：由冻结验收项直接生成的场景。
2. `history`：选择 catalog 中 `control_surfaces` 与本次 `touched_control_surfaces` 有交集的全部条目，不得人工漏选。
3. `exploration`：针对仍有不确定性的受影响边界做少量新探针，不把探索通过写成完整证明。
4. `uncovered`：没有可执行场景、缺少能力或证据、以及 catalog 未覆盖的受影响面。

四类结果分别报告，不合并、不互相抵消。历史条目无匹配不等于历史风险为零；应明确 catalog 覆盖范围。

## 多样本与判定

确定性场景默认一个 fresh-context sample；只有修改路由、循环、worker 清场等关键模型决策，或首次结果不稳定时，才使用契约规定的三个 samples。每个 sample 不继承其他 sample 的结论或实现理由，并记录独立结果。报告样本数、通过数、失败数、通过率与二元结果方差；单次 PASS 只能证明该次样本通过，不能证明稳定。

candidate 只有在已知验收不回归、历史逃逸不复现，且差分证据未显示稳定性下降时才可通过。探索 finding 单列；未覆盖范围始终保留。

## 有限修订

每轮只允许根据新行为证据修订 candidate 规则一次，然后用同一场景集合和新的 fresh samples 复验。最多三次规则修订；任意连续一次修订没有改善预先冻结的失败数或稳定性指标，立即停止并升级，保留 control/candidate 原始证据。不得递归规划、启动无界自我改写或以更换判定器制造改善。

## 副作用边界

允许只读检查和隔离临时工作区中的可丢弃运行。不得直接执行外部副作用，包括发送消息、发布、部署、安装、push、tag、真实审批或生产写入；只报告需要另行授权的动作。清理本次临时资源后输出机器契约规定的四类结果与停止原因。
