<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-105518 -->
<!-- 功能名称: converge-013-integration -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/04_testing/unit-tests/F20260821-105518-converge-013-integration-test-plan.md -->
<!-- 创建时间: 2026-08-21T10:57:19+08:00 -->

# E2E：Converge 0.13.0 双运行时诊断

## 用例

1. `PYTHONDONTWRITEBYTECODE=1 bash scripts/check.sh`：全部 Suite 契约与 helper 测试通过。
2. `bash install.sh --doctor --target codex --offline`：Codex Suite complete。
3. `bash install.sh --doctor --target claude --offline`：Claude Code Suite complete。
4. `git diff --check`：无空白错误。

独立差分行为验收由父控制器另派 evaluator；本执行者只交付可运行的 eval 契约与场景入口。
