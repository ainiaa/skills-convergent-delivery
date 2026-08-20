<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-165451 -->
<!-- 功能名称: converge-planned-execution -->
<!-- 阶段: E2E 测试 -->
<!-- 前置文档: docs/04_testing/unit-tests/F20260820-165451-converge-planned-execution-test-plan.md -->

# E2E 场景

1. 在临时目录安装完整 Suite，确认 Codex/Claude Code 均发现四个入口。
2. 输入 PDLC 计划，确认仅返回一个 fresh `pdlc-run`，不生成内部 PDLC 阶段。
3. 输入三个任务，其中两个独立、一个依赖前两者，确认生成两个 wave；Batch v1 仍顺序执行。
4. 将证据标记为陈旧并加入计划外文件，确认最终审计不能返回 complete。
5. 前向模拟长上下文无活动：先软探测，再只恢复原任务一次；有运行进程时不触发中断。

## 执行结果

- 四入口临时安装、卸载和 doctor：通过。
- PDLC 单任务屏障、依赖 wave、路径冲突串行：通过。
- 陈旧证据与计划外 diff 阻止 complete：通过。
- watchdog 为宿主行为协议，由独立前向审查核对触发条件；未人为等待 180 秒。
- 全量 `bash scripts/check.sh`：106 个测试通过。

测试未访问外部服务，未执行发布。
