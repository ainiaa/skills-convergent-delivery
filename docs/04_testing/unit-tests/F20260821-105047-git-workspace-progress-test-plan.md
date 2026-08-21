<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-105047 -->
<!-- 功能名称: git-workspace-progress -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260821-105047-git-workspace-progress-arch.md -->

# 测试计划

聚焦命令：

- `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_delivery_progress.py`
- `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_delivery_report.py`

覆盖场景：staged + unstaged + untracked 正常聚合；tracked/untracked binary 边界；dirty baseline；worker/state 伪造统计；Git worktree 不可读异常；既有 status 去重与 report 简洁模式回归。

## 红灯证据

1. 首个测试：10 tests，9 pass、1 error，exit 1；首因 `workspace_change_summary` 不存在。
2. progress 扩展契约：13 tests，9 pass、3 error、1 failure，exit 1；除入口缺失外，status 尚未显示父 Git 累计。
3. report 契约：13 tests，11 pass、2 error，exit 1；首因 JSON 尚无 `workspace_changes`。

## 绿灯证据

progress 13/13、report 13/13，合计 26/26 通过，均 exit 0；`git diff --check` exit 0。

## 自审记录

5/5 验收标准均有测试或命令证据；覆盖正常、边界、异常与信任边界，无空断言。
