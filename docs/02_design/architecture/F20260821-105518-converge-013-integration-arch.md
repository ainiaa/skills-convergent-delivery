<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-105518 -->
<!-- 功能名称: converge-013-integration -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260821-105518-converge-013-integration-prd.md -->
<!-- 创建时间: 2026-08-21T10:57:19+08:00 -->

# 架构设计：Converge 0.13.0 Suite 集成

## 1. 背景与目标

T1–T4 已提供各自的协议和实现。本切片仅扩展现有 Suite 注册、根控制说明和发布表面，使五个 Skill 共享一致的安装与验证入口。

### 非目标

- 不在根 `converge` 中复制 PDLC 的 requirements/design/TDD/implementation/review。
- 不新增运行时、状态机或依赖。
- 不由本执行者冒充独立 reviewer/evaluator。

## 2. 整体架构

```text
Plan Contract v3
  ├─ checkpoint=same_session → 同工作区顺序任务，无 commit 门禁
  └─ checkpoint=cross_session → converge-batch，本地 commit 授权门禁

converge（控制面）
  ├─ Provider 内实现循环：红灯 → 最小实现 → 绿灯，重复问题停止
  ├─ 单任务双轴审查：spec → quality，每轴一次修复+一次复核
  └─ 全局集成审查：全部任务后一次，只查跨任务风险

converge-eval（独立验收）
  └─ known_acceptance | history | exploration | uncovered
```

父控制器从 Git 读取整个工作区累计统计；Codex UI 的单步角标只表示当前动作，两者不得互相替代。

## 3. 模块职责

| 模块 | 最小变更 | 依赖 |
|---|---|---|
| `install.sh` | 五 Skill 注册与 eval 强制资源 | 现有数组/doctor |
| `scripts/check.sh` | 官方验证与 eval 契约测试 | 现有 Python unittest |
| `SKILL.md` | Plan v3、循环、报告、Git 可见性总控 | T1–T4 契约 |
| `references/execution-control.md` | 三循环唯一终止规则 | Review Protocol v2 |
| `README.md` | 双运行时使用说明和 0.13.0 行为 | 安装/控制协议 |
| `VERSION`/`CHANGELOG.md` | 发布元数据 | 无 |

## 4. 关键流程与终止条件

1. 实现循环：有效红灯后最小实现；目标测试绿且新鲜验证通过即停；同一问题修复后复现或无客观改善立即停。
2. 单任务双轴审查循环：spec 先于 quality；每轴最多一次修复和一次复核；重复 finding 或无进展即阻塞。
3. 全局集成审查循环：所有任务完成后只运行一次，只覆盖跨任务风险；finding 可进行一次 closure，随后停止。

## 5. 兼容性与风险

| 风险 | 应对 |
|---|---|
| 安装器漏掉 eval 子资源 | 契约逐路径断言 + offline doctor |
| README 与控制协议漂移 | 同一聚焦测试断言 Plan v3、checkpoint 和四类报告 |
| 把场景通过写成绝对无问题 | 强制保留 `uncovered`，禁止“未发现任何问题”措辞 |
| 误把当前任务角标当累计 diff | 根 Skill/README 明确父 Git 累计真值 |

## 6. 自审记录

- 时间：2026-08-21T10:57:19+08:00
- PRD 的 5 项功能均映射到模块与验证；无 API、数据库或部署变更。
- 问题数：0；自动修复：0；需人工确认：0。
