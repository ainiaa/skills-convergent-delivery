<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-004423 -->
<!-- 功能名称: converge-control-kernel -->
<!-- 阶段: E2E 测试 -->
<!-- 前置文档: docs/04_testing/unit-tests/F20260821-004423-converge-control-kernel-test-plan.md -->

# E2E 场景

1. Provider：在临时 Skill root 选择并冻结 workflow，修改 manifest/入口/closure 后恢复应阻塞。
2. Native fallback：空 HOME、无 PDLC 时 select 成功并产生完整 Native Binding。
3. Runtime：Codex 完整能力进入 automatic；Claude 无 query、single-context 进入 manual。
4. Progress：worker milestone 后，父 query heartbeat 不增加 objective revision；文本相同但 host lifecycle 改变仍展示。
5. Self-host：创建完整只读 snapshot，在空 HOME auto 选择 Native；可写 workspace 不能伪装，修改目标 workspace 后 snapshot 仍有效。
6. Report：ready 默认只显示 summary；blocked 或 detail 有界显示 Provider、worker 与 check diagnostic。
7. 安装：offline Codex doctor 验证所有运行文件随包安装。

执行入口：`bash scripts/check.sh` 与冻结计划三条 verification 命令。
