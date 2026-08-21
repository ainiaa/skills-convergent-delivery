<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-102230 -->
<!-- 功能名称: plan-granularity -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260821-102230-plan-granularity-arch.md -->
<!-- 创建时间: 2026-08-21T10:28:50+08:00 -->

# Plan Granularity 测试计划

| 场景 | 覆盖 | 结果 |
|---|---|---|
| vertical slice / wide refactor / integration | 正常、类型边界、integration 依赖异常 | 通过 |
| long 单 task 多 outcomes | 多独立结果异常与可操作 blocker | 通过 |
| schema v3 long 单 outcome | 真正单结果正常流程 | 通过 |
| 有依赖多任务 | wave 与 sequential 正常流程 | 通过 |
| same_session / cross_session | commit 门禁正常与边界 | 通过 |
| 旧 long 单 task | 兼容迁移无法证明粒度时阻塞 | 通过 |

红灯：`PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-plan/scripts/test_plan_check.py`，20 个测试中 8 个失败；schema v3 未支持、旧 long 单任务错误放行、无可操作多 outcome blocker。

绿灯：同命令 20/20 通过，耗时 2.153s；冻结计划额外验证得到 `sequential`、`commit_authorization_required=false`。

## 自审记录

- 验收覆盖：7/7。
- 场景：正常、边界、异常和旧协议兼容均覆盖。
- 测试位置：沿用既有 `skills/converge-plan/scripts/test_plan_check.py`。
- 一次复查：0 个缺口。
