<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-215348 -->
<!-- 功能名称: converge-runtime-vnext -->
<!-- 阶段: E2E 测试 -->
<!-- 前置文档: docs/04_testing/unit-tests/F20260820-215348-converge-runtime-vnext-test-plan.md -->

# E2E 验证

1. 在临时 HOME 和 provider root 中执行 provider 选择、冻结、修改 closure、恢复，期望明确 blocked。
2. 在临时 lease/state root 中写入真实 v5，读取 v6，登记 working worker 后尝试 complete，期望拒绝；更新宿主终态后完成。
3. 将同一已验证 state 分别从文件和 stdin 生成 JSON report，逐字比较。
4. 执行 `scripts/check.sh`、`bash install.sh --doctor --target codex --offline --source <repo>` 和 `git diff --check`。

所有场景使用临时目录，不修改用户配置、不创建发布或 Git 写操作。
