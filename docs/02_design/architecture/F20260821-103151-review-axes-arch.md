<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-103151 -->
<!-- 功能名称: review-axes -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260821-103151-review-axes-prd.md -->

# Review 双轴编排设计

## 边界

`converge-review` 仍是只读 reviewer，只定义单次请求/结果；根级编排契约定义控制器如何串联审查与修复，不新增运行时代码。

## 状态流

单任务为 `spec initial -> optional repair -> spec re-review -> quality initial -> optional repair -> quality re-review`。任一轴重复 finding 指纹、修复后源码指纹未变化、预算耗尽仍有 defect 时进入 blocked。所有任务两个轴通过后，计划仅启动一次 `integration` initial；其可使用同一固定修复/复核预算。

## 协议

Protocol v2 新增 `axis`、`phase`、`task_id`；finding 与 source fingerprint 保持既有语义。`integration` 请求拒绝 task-local finding。v1 请求按原协议读取，不推断轴或加入 v2 编排。

## 自审记录

2026-08-21：覆盖全部 P0；不涉及 API、数据库或新依赖；兼容边界明确。
