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
