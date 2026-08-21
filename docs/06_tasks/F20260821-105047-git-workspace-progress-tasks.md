<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-105047 -->
<!-- 功能名称: git-workspace-progress -->
<!-- 阶段: 任务 -->
<!-- 前置文档: docs/06_tasks/F20260821-converge-013-review-loop-plan.json#T4 -->

# 冻结 T4 追溯清单

本文件只追溯既有 T4，不重新规划或拆分执行范围。

- [x] `TF20260821-105047-01-test`：先写 tracked/untracked 红灯，再补 staged、binary、dirty baseline、Git failure 与 parent-trust 契约。
- [x] `TF20260821-105047-02-impl`：复用 state 的 workspace/baseline，实现最小 Git 汇总并接入 progress/report。
- [x] `TF20260821-105047-03-review`：单次自审、修复路径换行处理、运行两组聚焦测试与 diff check。
