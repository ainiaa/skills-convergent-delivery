<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-102230 -->
<!-- 功能名称: plan-granularity -->
<!-- 阶段: E2E 测试 -->
<!-- 前置文档: docs/04_testing/unit-tests/F20260821-102230-plan-granularity-test-plan.md -->
<!-- 创建时间: 2026-08-21T10:28:50+08:00 -->

# Plan Granularity E2E

使用真实冻结计划执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-plan/scripts/plan_check.py validate --input - < docs/06_tasks/F20260821-converge-013-review-loop-plan.json
```

结果：退出码 0；normalized schema v3；waves 为 T1→T5；`execution_mode=sequential`；`commit_authorization_required=false`。冻结计划文件未修改。
