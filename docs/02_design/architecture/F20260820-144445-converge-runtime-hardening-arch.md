<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-144445 -->
<!-- 功能名称: converge-runtime-hardening -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260820-144445-converge-runtime-hardening-prd.md -->

# 架构设计：Converge 运行时闭环增强

## 1. 设计原则

- 保持三个用户 Skill，不新增编排层。
- 能用现有状态和宿主工具完成的，不新增 Python 抽象。
- 宿主差异放入 Batch 按需 reference；根 Skill 不加载。
- 模拟 E2E 与真实 Agent E2E 分开标记，禁止互相替代。

## 2. 组件变更

| 组件 | 变更 | 复用 |
|---|---|---|
| `install.sh` | 新增 `--doctor` 和 Suite 完整性版本展示 | 既有 target/source/mandatory files |
| `scripts/delivery_report.py` | 读取 Schema v5，复用 `delivery_next.validate_state`，输出 JSON/text | 既有 ledger、handoff、acceptance |
| `converge-batch/references/runtime-adapters.md` | Codex/Claude 的探测、派发、等待、恢复、receipt 契约 | 既有 Batch Protocol v1 |
| Batch 测试 harness | 用 fake host 验证两批接力、断线恢复和重复派发保护 | 既有 `batch_state.py` |
| activation reference | 提供关键词与可复制 AGENTS 片段 | frontmatter 和默认隐式调用 |

## 3. Doctor 与版本

`suite_status(runtime)` 检查三个入口：必须都是 symlink、Skill 名正确，并解析到 `converge` 根及其两个 `skills/` 子目录。输出：

```text
Codex: 0.8.0 (complete)
Claude Code: 0.8.0 (incomplete: missing converge-review, converge-batch)
```

`--doctor` 额外检查 Bash、Git、Python >=3.9、mandatory Suite 文件和执行引擎探测。PDLC 缺失不是失败，因为 native 是合法降级；入口残缺或必需依赖缺失退出非零。doctor 只读，不获取安装锁。

## 4. 确定性报告器

输入为 Schema v5 JSON。先调用现有结构校验，再生成：`outcome`、`goal`、`verification`、`completed_rounds`、`repaired_issues`、`pending_items`、`acceptance`、`next_action`。JSON 是机器接口，text 是稳定中文回执；不执行新检查或写状态。

待处理数 = 非 fresh pass 验收项数量 + 非空 `handoff.open_issues` 的一个汇总项。这样口径确定，且不猜测自然语言中有几个问题。

## 5. Batch 运行时适配

Batch Skill 根据宿主能力读取对应段落：

- Codex：创建新任务 → 保存 task/thread ref → 有界等待 → 读取结构化 receipt；连接中断先查询原 ref，不重派。
- Claude Code：使用可用的新上下文任务能力；无法获得稳定 ref/等待能力时输出 capsule 并暂停。
- 其他宿主：仅手工交接，不伪造自动调度。

运行时层不修改 Batch 状态规则。状态必须先写入 `dispatching`，成功取得 ref 后才写 `running`。

## 6. 验证设计

1. 安装器测试：完整/残缺/错源入口、doctor 依赖、版本展示。
2. 报告器测试：ready/decision/blocked、陈旧验收、轮数和问题数。
3. Batch fake-host E2E：两批接力、断线恢复、不确定派发阻塞。
4. 独立真实 Agent：隔离临时仓库执行一次两批计划，保存任务引用和回执结论。
5. 全量回归和三个 Skill 结构校验。

## 7. 风险与取舍

| 风险 | 处理 |
|---|---|
| 宿主工具名称变化 | reference 描述能力与当前映射，探测失败降级手工 capsule |
| 报告器复制状态校验 | 直接复用 `validate_state`，不复制 Schema |
| E2E 自称真实但只跑 fake | 结果显式标注 simulated/real |
| 自动触发仍受运行时控制 | 提升 frontmatter 与测试覆盖，不作 100% 承诺 |

## 8. 自审记录

- PRD P0/P1 覆盖：6/6。
- 无新增依赖、后台进程或用户 Skill。
- 安全边界保持：doctor/report 只读，dispatch 不确定即阻塞。
- 结论：通过。

---
作者：Jeff.Liu
状态：已评审
