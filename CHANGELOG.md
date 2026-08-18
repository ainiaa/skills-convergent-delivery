# 变更日志

本项目的重要变更记录在此文件中，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- 建立 `convergent-delivery`，提供有限阶段的需求实现、验证、复查和交接流程。
- 同时支持 Codex 与 Claude Code，并使用单一 Skill 源文件避免流程规则漂移。
- 新增 `VERSION`、`install.sh` 及安装器回归测试；支持安装、升级、卸载与版本检查。
- 新增 worktree 与任务级 writer lease，支持不同任务并行，并阻止同一 worktree 双写或同一任务重复执行。
- 新增 `delivery_engine.py` 与回归测试：按已安装或源码中的实际 PDLC Skill 能力确定性选择 `pdlc-v1` 或 `native-v1`，支持自动选择、强制 PDLC 的环境阻塞和活动任务引擎粘性。
- 状态 Schema v4 新增冻结的执行引擎和验收证据新鲜度；`complete` 必须具有至少一项新鲜、通过的验收证据。
- 新增 PDLC 路由、引擎恢复、陈旧验证、根因无进展和脏工作区压力场景。
- lease helper 改用 Python 3.9 兼容的 UTC 写法，避免系统 Python 版本较低时无法获取或续期 lease。
- 新增结果驱动的“交付回执”规范：区分可交付、需关注、需确认和环境阻塞；支持默认摘要、业务验收矩阵、单项决策卡和按需技术证明包。
- ledger 新增增量回执信息，避免连续检查时反复输出相同的流程、命令和文件清单。

### 变更

- Skill 正式名称从 `convergent-delivery` 调整为更易记的 `converge`；安装器会安全迁移指向同一源码的旧软链接。
- 状态 Schema 先升级为 v3：共享跨运行时 ledger，并用 lease、writer 与 revision 保护写入和恢复。
- 状态写入改为仅接受 stdin 候选 JSON，并由脚本推导正式路径，避免 `/tmp` 或任意路径成为恢复状态。
- `converge` 明确成为控制平面：兼容 PDLC 存在时，PDLC 独占需求产物、TDD、实现和阶段评审；`converge` 只负责范围、有限循环、lease、跨服务验收和最终报告。
- 只有 PDLC 不可用或用户明确选择原生模式时，才执行内置 TDD、语义复查和风险复查，避免双循环与重复状态机。
- 最终报告新增执行引擎、选择原因和验收证据新鲜度；陈旧、未知或未覆盖的检查不能宣称完成。
- 最终回复改为面向用户的摘要，不再强制输出内部状态机字段；存在待确认业务选择时，禁止把用户结论写成“已完成”。

### 文档

- 补充 PDLC / 原生引擎职责边界、选择规则、恢复策略和能力探测方式。
