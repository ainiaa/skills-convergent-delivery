<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-105047 -->
<!-- 功能名称: git-workspace-progress -->
<!-- 阶段: 需求 -->
<!-- 前置文档: docs/06_tasks/F20260821-converge-013-review-loop-plan.json#T4 -->
<!-- 创建时间: 2026-08-21T10:50:47+08:00 -->

# Git 工作区累计进度 PRD

## 背景与目标用户

Codex 单步角标只描述最近一次工具动作，不能代表整个任务的累计改动。目标用户是需要从父控制器进度和最终回执判断当前工作区真实变化的维护者。

## 目标

父控制器直接读取 Git 工作区真值，在进度里程碑与最终报告中显示累计文件和行数，并明确脏基线下这些累计值不能归因于当前任务。

## 用户故事

1. 作为维护者，我要同时看到 staged、unstaged 与 untracked 的累计变化。
2. 作为审查者，我要二进制文件计入文件数，但不看到伪造的增删行。
3. 作为任务负责人，我要区分 Codex 单步角标、worker 回执和父控制器 Git 累计真值。
4. 作为运行维护者，我要在 Git 暂时不可读时得到结构化降级，而不是报告进程崩溃。

## 功能清单

- P0：聚合 tracked staged/unstaged 与 untracked 文件。
- P0：分别统计文件数、文本增删行和二进制文件数。
- P0：脏 baseline 显示“不归因于本任务”的说明。
- P0：忽略 worker 或 state 中自报的累计统计。
- P0：progress 保持去重，final report 保持简洁。
- P0：Git 读取失败返回结构化 unavailable。

## 验收标准

1. 聚焦测试覆盖 staged、unstaged 和 untracked 后得到唯一累计文件数及正确增删行。
2. tracked/untracked 二进制均计文件与 binary count，增删行保持 0。
3. dirty baseline 显示累计包含既有改动且不能归因当前任务。
4. 伪造统计不能覆盖父控制器的实时 Git 结果；Git 不可读时报告仍 exit 0。
5. 两个既有聚焦测试脚本通过，且 `git diff --check` 通过。

## 非功能要求

不新增依赖；复用现有 progress/report/state；只运行冻结 T4 指定验证；保持固定只读 Git 命令和有界输出。

## 不在范围内

不修改 Codex UI 角标，不按本任务 owned paths 归因行数，不保存逐文件明细，不执行全仓 check、commit、tag、push、publish、install 或 ship。

## 自审记录

2026-08-21：4 条用户故事、6 项 P0 与 5 条可执行验收标准已覆盖正常、边界和异常场景；范围来自冻结 T4，未创建递归计划。
