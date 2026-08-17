# 变更日志

本项目的重要变更记录在此文件中，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- 建立 `convergent-delivery`，提供有限阶段的需求实现、验证、复查和交接流程。
- 同时支持 Codex 与 Claude Code，并使用单一 Skill 源文件避免流程规则漂移。
- 新增 `VERSION`、`install.sh` 及安装器回归测试；支持安装、升级、卸载与版本检查。
- 新增 worktree 与任务级 writer lease，支持不同任务并行，并阻止同一 worktree 双写或同一任务重复执行。

### 变更

- Skill 正式名称从 `convergent-delivery` 调整为更易记的 `converge`；安装器会安全迁移指向同一源码的旧软链接。

### 文档

- 补充跨运行时安装、状态保存位置、运行时命令、安装互斥与多窗口维护约定。
