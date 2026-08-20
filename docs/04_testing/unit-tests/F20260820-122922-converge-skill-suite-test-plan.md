<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-122922 -->
<!-- 功能名称: converge-skill-suite -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260820-122922-converge-skill-suite-arch.md -->
<!-- 创建时间: 2026-08-20T04:32:00Z -->

# 测试计划：Converge Skill Suite

## 1. 测试范围

覆盖三个 Skill 的结构与职责、Suite 安装、Batch 状态协议及现有单任务 helper 回归。不测试真实 GitHub 网络、真实 Codex/Claude 任务创建和生产发布。

## 2. 测试策略

- [x] Python 单元测试：Batch 状态和安装器。
- [x] 契约测试：Skill frontmatter、职责边界、协议字段。
- [x] 集成检查：`bash scripts/check.sh` 执行全部现有与新增测试。
- [x] 前向场景：独立上下文验证触发、委托和中断恢复。

## 3. 测试用例

| 编号 | 测试用例 | 预期结果 | 优先级 |
|---|---|---|---|
| UT-001 | Codex/Claude 安装 Suite | 每端存在三个指向正确源码的链接 | P0 |
| UT-002 | 任一目标冲突 | 安装前失败，不留下部分新链接 | P0 |
| UT-003 | 卸载 Suite | 仅移除可识别的三个链接 | P0 |
| UT-004 | 初始化合法 Batch 状态 | 私有原子文件写入派生路径 | P0 |
| UT-005 | 非法跳转、陈旧 revision、计划漂移 | helper 拒绝写入且保留旧状态 | P0 |
| UT-006 | 重复 dispatch 或 receipt 不匹配 | helper 拒绝完成 Batch | P0 |
| UT-007 | pause 后新派发、Batch 阻塞但计划仍 active | helper 拒绝非法状态，恢复 active 后才可派发 | P0 |
| UT-008 | 越序/停止后派发、伪造 commit/tree | helper 拒绝非当前批次和不可解析的 Git receipt | P0 |
| UT-007 | 缺少最终集成证据时完成计划 | helper 拒绝 complete | P0 |
| CT-001 | 三 Skill frontmatter 与职责 | 描述互斥，reviewer/scheduler 保持只读边界 | P0 |
| CT-002 | Review/Batch 协议 | 包含新鲜度、胶囊、receipt、暂停恢复和有限关闭规则 | P0 |
| RT-001 | 现有 helper 回归 | engine、lease、state、reporting 全部通过 | P0 |

## 4. 通过标准

- 所有新增测试先因能力缺失出现有效红灯。
- 实现后 `bash scripts/check.sh` 退出码为 0。
- 不新增第三方依赖。
- 最终 diff 与 PRD 验收逐项对应。

## 5. 自审记录

- 验收标准覆盖：7/7。
- 正常、边界和异常场景均包含。
- 测试断言状态行为和协议不变量，避免只固定完整文案。

---
创建日期：2026-08-20
作者：Jeff.Liu
状态：已评审
