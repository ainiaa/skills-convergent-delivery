<!-- PDLC-TRACE -->
<!-- 功能ID: B20260821-191424 -->
<!-- 功能名称: converge-control-contract-closure -->
<!-- 阶段: review -->
<!-- 前置文档: references/execution-protocol.md -->
<!-- 创建时间: 2026-08-21T19:14:24+08:00 -->

# 缺陷记录：Converge 控制契约闭环

作者：Jeff.Liu

## 根因

- Reviewer 公共协议 v2 与 Single State Review v3 的模式、状态和值域不一致，且没有可执行转换器。
- 当前完成态只校验自由文本验收和源码摘要，未强制绑定真实 Git Source Receipt 与命令 Evidence Receipt。
- Codex 计划确认可与阶段推进在同一 revision 混写；控制快照未冻结实际调用的 plan/review/eval 规则。
- Eval 只有声明性 JSON；报告会合并不同待处理数量、接受无限文本，并在 Git 不可读时误报 ready。
- 安装测试漏掉 `converge-eval`，崩溃遗留锁无法恢复，doctor 输出整段 Provider JSON；仓库误跟踪运行时锁文件。

## 修复

- 新增 Review v2→v3 确定性适配器，统一内部 SHA-256 finding 身份和值域校验。
- 当前 Schema v10 complete 强制 Source Receipt v2 与逐项 Evidence Receipt v1；旧状态仅保守读取。
- 计划确认与报告历史均改为独立 revision；Controller Snapshot Protocol v8 冻结实际控制面。
- 新增 Eval 确定性 kernel；报告限制文本、分别计数、支持无变化短回执并对 Git 不可读降级。
- 完整安装五个 Skill，安全接管死 PID 的陈旧锁，精简 doctor，并删除仓库中的运行时锁文件。

## 验证

- RED：新增协议、证据、计划确认、快照、评估、报告、安装锁和仓库卫生测试均在实现前失败。
- GREEN：5 个官方 Skill 校验与 298 项全量测试通过；Codex、Claude Code Suite 均为 0.18.0 complete，Provider doctor 输出已收敛为摘要。
- EVAL：确定性差分选择覆盖 3 个匹配的历史逃逸场景，3 个样本均通过；独立 fresh-context evaluator 超过有限等待窗口后被主动中断，作为 uncovered 保留，不伪报通过。

## 范围说明

- 未增加外部依赖、后台进程或新的 Agent 调度层。
- Eval helper 只负责确定性选择、统计和停止规则；fresh-context 样本仍由宿主按 Runtime Adapter 能力执行。
