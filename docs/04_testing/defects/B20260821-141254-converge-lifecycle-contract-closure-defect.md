<!-- PDLC-TRACE -->
<!-- 功能ID: B20260821-141254 -->
<!-- 功能名称: converge-lifecycle-contract-closure -->
<!-- 阶段: review -->
<!-- 前置文档: references/execution-control.md -->
<!-- 创建时间: 2026-08-21T14:31:14+08:00 -->

# 缺陷记录：Converge 生命周期契约闭环

作者：Jeff.Liu

## 根因

- blocked 被当作完全不可变终态，宿主中断成功后无法登记真实清场结果。
- 清场回执的能力模式由状态写入者自由填写，没有绑定会话协商出的 Runtime Adapter 能力。
- Batch 文档要求 `controller-delegate`，但状态只验证普通 `batch-executor` 与 Git 回执，没有验证子 Converge run 已完成并清场。
- complete 可缺少任务身份，blocked action 丢失真实原因；组合场景测试只覆盖路由函数。

## 修复

- blocked 保持失败终态，但允许后续 revision 只更新既有 worker 的宿主生命周期与清场回执；其他任务事实、进度和 worker 集合冻结。
- Runtime Binding 使用 canonical fingerprint 冻结；清场回执由适配器推导模式并绑定该指纹。
- Batch worker 改为 `controller-delegate`，持久化唯一 `delegate_run_id`；receipt v2 校验完整子 Converge complete state、清场、repo、workspace、baseline、task 和 Provider。
- 所有正常终态 action 带任务或计划身份，blocked 保留原始原因；运行场景直接组合生产状态机验证清场转换。
- 协议升级后仅允许旧内容寻址快照执行精确 lease release，避免自修改任务无法清场；旧快照的其他 helper 继续阻塞。

## 验证

- RED：运行时回执、complete 身份和 blocked 清理用例在实现前稳定失败。
- GREEN：`bash scripts/check.sh` 的 249 个测试与 5 个官方 Skill 校验全量通过。
- 安装诊断：Codex Suite `0.15.0` complete；未修改 Claude Code 安装。
- 回归覆盖正常清场、伪造 Binding、blocked 事实改写、重复 delegate run、子状态缺失以及真实终态原因。

## 范围说明

- 未增加后台守护进程、外部依赖或新的调度层。
- Runtime Binding 证明当前控制器采用了哪种已协商能力；宿主查询结果仍由持有 writer lease 的父控制器负责如实登记。
