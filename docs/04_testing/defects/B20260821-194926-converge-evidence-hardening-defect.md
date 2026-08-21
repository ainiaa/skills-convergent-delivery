<!-- PDLC-TRACE -->
<!-- 功能ID: B20260821-194926 -->
<!-- 功能名称: converge-evidence-hardening -->
<!-- 阶段: impl -->
<!-- 前置文档: 无 -->
<!-- 创建时间: 2026-08-21T20:05:39+08:00 -->

# Converge 证据闭环缺陷记录

## 根因分析

Single State 写入器使用调用方提交的旧 `schema_version` 决定是否执行完成证据门禁，把“读兼容”错当成“写授权”。Eval helper 只统计调用方提交的 `pass/fail` 字符串，没有绑定场景、对照源、judge、worker 和原始证据。宿主计划、runtime 与进度又没有标注事实来源，容易把控制器自述误当成已验证事实。同时 Snapshot 漏了可路由的 Batch 闭包，Review 适配器也只有库函数而无可执行入口。

## 影响范围

- 旧 Schema 调用方可以在没有 Source/Evidence Receipt 时新写 `complete`。
- Eval 可被 `samples=["pass"]` 伪造成功，`exploration/uncovered` 不反映真实覆盖。
- 宿主计划回执、worker heartbeat 和清场证据的信任级别不可见。
- 自修改运行中 Batch 调度契约可漂移，Review 结果需模型手工转写。

## 修复方案

1. 所有持久化 complete 写入无条件执行 v10 完成证据校验；旧 Schema 只保留读取和只添加迁移。
2. Eval Contract v2 改用指纹化 Sample Receipt，绑定 scenario/class、control/candidate、judge、worker、evidence source 与双侧结果，由 receipts 推导 `exploration/uncovered`。
3. Runtime Binding/cleanup receipt v2 与 Progress Receipt 显式标注 `host_observed/controller_attested`；native plan 只接受 `host_observed` 确认。
4. Controller Snapshot 补齐 Batch SKILL、契约和 helper；Review Contract 新增 stdin-only CLI；doctor 提示激活边界；Batch 文档统一 Receipt v4。

## 回归测试

- 旧 Schema complete 绕过：先确认旧实现错误放行，修复后精确用例通过。
- Eval receipt：旧 samples、篡改指纹、错误 source/judge/scenario 均有负例，exploration/uncovered 有确定性断言。
- 证据等级：runtime、tree/restrict cleanup、milestone、heartbeat 和 plan ack 均有可执行断言。
- Snapshot、Review CLI 和 doctor 先验证红灯，再完成最小修复。
- 全量验证：`bash scripts/check.sh` 的 5 个官方 Skill validator 与 309 个自动化测试全部通过；Codex/Claude doctor 均为 `0.19.0 complete`；`git diff --check` 通过。

## 假设与说明

纯 Skill 无法自行获得所有宿主工具回执，因此本次不伪造加密信任根；只把宿主观测与控制器声明显式降级分类，并禁止后者冒充 native plan 成功回执。

## 定向修复复核

- Eval 对每个 required acceptance/selected history scenario 分别校验至少三个 distinct `worker_ref`；无关 exploration 不能补足样本数。新增回归用例先红后绿，Eval 聚焦测试 8 项通过。
- Snapshot trusted runner 仅精确放行冻结的 Batch `batch_next.py` 与 `batch_state.py`；真实 `run` 用例通过，Review helper 与 Skill 文档保持不可执行。
- 交付报告的“已验证范围”仅由结构化 `fresh/pass` acceptance 与 `pass` checks 派生；`handoff.last_verification` 只以 `controller_attested` 说明展示。新增回归用例先红后绿，报告聚焦测试 17 项通过。

## 上线前待办

- 独立 quality 复核发现 `ledger.checks` 只有 `stage/command/result`，没有 `source_fingerprint`、freshness 或 Evidence Receipt；历史 `pass` check 仍可能被报告为当前“已验证范围”。Finding：`cb541adddb6df6936aa1a68dba17d6f59754e2ad969db7cd2aced2c0e207532d`。
- 本轮唯一修复预算已用尽，状态保持 blocked；下一轮应先为 checks 增加源码绑定，再允许报告消费。
- 无数据迁移或外部发布动作。本次未执行 commit、tag、push、publish 或 install。
