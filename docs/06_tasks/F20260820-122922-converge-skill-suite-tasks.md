<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-122922 -->
<!-- 功能名称: converge-skill-suite -->
<!-- 阶段: 任务 -->
<!-- 前置文档: docs/01_requirements/prd/F20260820-122922-converge-skill-suite-prd.md -->
<!-- 创建时间: 2026-08-20T04:30:05Z -->

# Converge Skill Suite 任务清单

| ID | 标题 | 类型 | 状态 | 前置依赖 |
|---|---|---|---|---|
| TF20260820-122922-01-test | 新增 Suite 安装与协议失败测试 | test | ✅ | 无 |
| TF20260820-122922-02-feat | 精简 `converge` 为单任务执行 Skill | feat | ✅ | 01 |
| TF20260820-122922-03-feat | 新增 `converge-review` 与审查契约 | feat | ✅ | 01 |
| TF20260820-122922-04-feat | 新增 `converge-batch`、状态协议和 helper | feat | ✅ | 01、03 |
| TF20260820-122922-05-feat | 全套预检并安装、升级和卸载三个 Skill | feat | ✅ | 02、03、04 |
| TF20260820-122922-06-docs | 更新 README、CHANGELOG、VERSION 和使用指南 | docs | ✅ | 02、03、04、05 |
| TF20260820-122922-07-review | 全量验证和职责边界复查 | review | ✅ | 01-06 |
