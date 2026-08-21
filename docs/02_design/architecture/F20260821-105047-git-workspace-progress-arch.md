<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-105047 -->
<!-- 功能名称: git-workspace-progress -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260821-105047-git-workspace-progress-prd.md -->

# Git 工作区累计进度最小设计

## 数据流与真源

父控制器从 state 只取 `workspace` 和冻结的 `baseline.diff_fingerprint`。tracked 统计来自 `git diff HEAD`，因此同时覆盖 staged 与 unstaged；untracked 路径来自 `git ls-files --others --exclude-standard`，其文本行数由当前文件内容计算。worker receipt 和候选 state 中的自报统计一律不读取。

## 统计口径

- `file_count`：tracked 与 untracked 相对路径去重后的并集。
- `lines_added/lines_deleted`：tracked 使用 Git numstat；untracked 文本全部计新增。
- `binary_file_count`：tracked 使用 numstat 的 `-/-`；untracked 复用 Git 的前 8000 bytes NUL 判定。二进制只计文件，不计行。
- `baseline_note`：`clean` 或空 diff 的 SHA-256 视为干净；其他指纹明确说明累计包含任务开始前已有改动，不能归因当前任务。

## 展示与降级

progress 的 worker 单步状态后单列“工作区累计”，并把该行纳入既有去重指纹。report JSON 保存结构化 summary；默认文本只显示 files、+lines、-lines、binary 和 baseline note。任何 Git/文件读取失败统一降级为 `status=unavailable,error=git_read_failed`，不抛出到用户报告。

## 自审记录

2026-08-21：设计覆盖全部 P0；复用现有模块和标准库，无新状态字段、依赖、逐文件报告或额外抽象。
