<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-215348 -->
<!-- 功能名称: converge-runtime-vnext -->
<!-- 阶段: 任务 -->
<!-- 前置文档: docs/01_requirements/prd/F20260820-215348-converge-runtime-vnext-prd.md -->

# Converge Runtime vNext 任务清单

| ID | 标题 | 类型 | 状态 | 前置依赖 |
|---|---|---|---|---|
| TF20260820-215348-01-test | 新 schema、worker 屏障与 v5 迁移行为测试 | test | ✅ | 无 |
| TF20260820-215348-02-test | controller/provider 漂移与 manifest 行为测试 | test | ✅ | 无 |
| TF20260820-215348-03-test | refactor 路由和传递依赖 fingerprint 行为测试 | test | ✅ | 无 |
| TF20260820-215348-04-test | stdin report 与 validator 门禁行为测试 | test | ✅ | 无 |
| TF20260820-215348-05-impl | 升级单任务状态与恢复控制 | impl | ✅ | 01, 02 |
| TF20260820-215348-06-impl | 增加 provider manifest 与 refactor 路由 | impl | ✅ | 02, 03 |
| TF20260820-215348-07-impl | 增加 stdin report 与正式 validator 环境 | impl | ✅ | 04 |
| TF20260820-215348-08-doc | 去重执行控制规则并更新用户文档/版本 | docs | ✅ | 05, 06, 07 |
| TF20260820-215348-09-review | 全量验证与交付评审 | review | ✅ | 08 |

任务总数：9。
