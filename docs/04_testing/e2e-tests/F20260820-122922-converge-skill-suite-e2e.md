<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-122922 -->
<!-- 功能名称: converge-skill-suite -->
<!-- 阶段: E2E 测试骨架 -->
<!-- 前置文档: docs/04_testing/unit-tests/F20260820-122922-converge-skill-suite-test-plan.md -->

# E2E 场景

1. 普通实现请求只触发 `converge`，PDLC 可用时不重复 native TDD。
2. 只读检查请求触发 `converge-review`，过程中没有工作树写入。
3. 多 Batch 计划触发 `converge-batch`，每批显式委托 `$converge`，同一 dispatch 不重复创建。
4. 中断后从状态恢复，计划变化或执行结果不确定时停止而不是猜测。
5. 所有 Batch 完成但整体集成证据缺失时，不宣称计划完成。

这些场景在发布前使用独立、全新 Agent 执行；当前仓库的确定性测试负责协议和状态不变量。
