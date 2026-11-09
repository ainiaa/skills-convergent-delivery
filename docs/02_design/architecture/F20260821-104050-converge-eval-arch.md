<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-104050 -->
<!-- 功能名称: converge-eval -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260821-104050-converge-eval-prd.md -->

# Converge Eval 最小设计

## 职责边界

`SKILL.md` 只表达何时使用、四类场景、差分/采样/停止规则和副作用边界。`evaluation-contract.json` 提供可机读预算与结果字段；根级 `evaluation-catalog.json` 是历史逃逸场景唯一数据源。无运行时 helper、无新依赖。

## 数据流

输入冻结验收项与 touched control surfaces → 冻结旧版 control → 以 catalog 交集形成 history 集合 → control/candidate 使用同一场景与样本预算 → 分别报告 known acceptance/history/exploration/uncovered → 按失败数和稳定性判断最多三次规则修订；首次无改善即停止升级。

## 机器契约

关键决策最少 3 个 fresh samples，报告 `sample_count/pass_count/fail_count/pass_rate/variance`。历史选择为 touched surfaces 与条目 surfaces 的非空交集，所有匹配条目必须纳入。外部副作用恒为禁止。

## 自审记录

2026-08-21：设计覆盖全部 P0；职责与 `converge-review`、实现控制器及发布流程分离；不涉及 API、数据库或依赖。

## 确定性 bridge 迁移记录

首次加入该 bridge 时，旧快照没有此入口，不能用新候选自证旧版 locked Eval 通过。该次实现以真实 bridge 集成回归验证；后续任务可以冻结已含 bridge 的旧版本后使用。默认模型模式和既有 v5 离线统计契约保持不变，以下 worker/multi-sample 规则仅适用于模型模式。

确定性桥的三项操作约束（首次 dogfood 实证）：冻结 suite 与 judge 文件必须以字节相同的形式同时存在于 control 与 candidate 两棵树——diff 检查会把两侧不一致的 suite/judge 路径判为 `candidate changes frozen judges, suite, or files outside allowed scope`，不存在"只在 control 侧、helper 自动豁免"的语义；创建 Controller Snapshot 必须使用 control 树自带的 `controller_snapshot.py`，否则新协议描述符会被冻结 evaluator 自带的校验器拒绝；把 suite 附着到 candidate 树时只允许新增 suite/judge 文件本身，附着操作的精确性由 `git diff --name-only` 的路径数核对。

仅 Controller Protocol v9→v10 首次把 Eval helper 加入 trusted runner 时，旧 v9 Snapshot 虽含 helper 但确定性拒绝执行。该次迁移必须保存旧 runner 的 unauthorized 证据、一个 fresh 独立只读 evaluator 报告和全量/定向测试，并把 locked differential 明确列为 `uncovered`；不得宣称 locked eval 通过。此 bootstrap 不适用于 v10 之后的任何变更。
