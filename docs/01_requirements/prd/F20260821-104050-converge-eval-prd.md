<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-104050 -->
<!-- 功能名称: converge-eval -->
<!-- 阶段: 需求 -->
<!-- 前置文档: docs/06_tasks/F20260821-converge-013-review-loop-plan.json -->
<!-- 创建时间: 2026-08-21T10:40:50+08:00 -->

# Converge 独立行为验收 PRD

## 背景与目标用户

Converge 自身规则变更缺少稳定的旧版对照、多样本证据和按受影响控制面自动选择的历史逃逸回归。目标用户是完成实现与审查后执行行为验收的独立 evaluator。

## 目标

新增职责独立的 `converge-eval`，以机器契约约束有限差分验收，不承担实现、代码审查或外部变更。

## 用户故事

1. 作为 evaluator，我要在自修改时冻结旧版 control，并让 control/candidate 使用相同场景和判定器。
2. 作为维护者，我要看到关键决策多个 fresh samples 的结果分布和方差，而不是一次 PASS。
3. 作为回归负责人，我要按 touched control surface 自动选择全部相关历史逃逸缺陷。
4. 作为决策者，我要分别看到 known acceptance、history、exploration 和 uncovered。

## 功能清单

- P0：冻结 control/candidate 差分契约。
- P0：关键决策至少三个 fresh samples，并报告样本分布和方差。
- P0：机器可读 catalog 按 control-surface 交集全选历史逃逸场景。
- P0：四类结果独立报告。
- P0：最多三次规则修订；连续一次无改进即停止并升级。
- P0：只允许只读与隔离临时工作区，不直接执行外部副作用。

## 验收标准

1. 聚焦契约测试验证旧版冻结、同场景差分和单次 PASS 不代表稳定。
2. 聚焦契约测试验证多样本统计字段与四类结果。
3. 聚焦契约测试验证 catalog 元数据及多 control surface 自动选集。
4. 聚焦契约测试验证修订预算、无改进停止和副作用边界。

## 非功能要求

不引入依赖；只修改冻结 T3 owned paths；Skill 短入口、机器细节独立；不运行最终全仓 check。

## 不在范围内

不接入 Suite 安装清单，不执行真实 evaluator 样本，不修改其他 Skill，不提交、发布、安装或 ship；Suite 集成与完整差分运行留给冻结 T5。

## 自审记录

2026-08-21：4 条用户故事、6 项 P0 和 4 条可执行验收标准已对应；范围与非目标明确，无需修复。
