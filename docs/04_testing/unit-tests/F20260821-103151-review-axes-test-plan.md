<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-103151 -->
<!-- 功能名称: review-axes -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260821-103151-review-axes-arch.md -->

# 测试计划

运行 `PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-review/scripts/test_review_axes_contract.py`。

- 正常：spec 必须先于 quality，结果不得合并或抵消。
- 边界：每轴 repair/re-review 预算均为 1。
- 异常：重复 finding 或源码指纹未变化必须 blocked。
- 集成：仅在全部任务双轴通过后启动，只覆盖跨任务风险。
- 兼容：v1 intent、blind、closure 可读且不推断 axis。

## 红灯证据

2026-08-21：4 个测试均因缺少 `references/review-orchestration.md` 出错，exit 1。

## 自审记录

4/4 验收标准均有测试；正常、边界、异常和兼容场景齐全。
