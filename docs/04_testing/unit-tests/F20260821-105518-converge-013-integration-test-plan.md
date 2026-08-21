<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-105518 -->
<!-- 功能名称: converge-013-integration -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260821-105518-converge-013-integration-arch.md -->
<!-- 创建时间: 2026-08-21T10:57:19+08:00 -->

# 测试计划：Converge 0.13.0 Suite 集成

## 验收映射

| 验收 | 测试 |
|---|---|
| 五 Skill 及 eval 资源完整 | `test_five_skills_*`、`test_release_registers_*` |
| Plan v3 与 checkpoint 语义一致 | `test_plan_v3_and_checkpoint_*` |
| 三类循环分别终止 | `test_three_bounded_loops_*` |
| 四类报告与父 Git 可见性 | `test_final_reporting_*` |
| 双运行时完整 | 两个 offline doctor |

## 场景

- 正常：五个 Skill、0.13.0、四类结果和所有强制资源存在。
- 边界：同会话多任务不要求 commit；跨会话 checkpoint 才进入 Batch 授权门禁。
- 异常：缺少 eval 入口/资源、循环停止语义或报告分类时聚焦测试失败；doctor 返回非零。

## 红灯证据

命令：`PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_skill_contracts.py`

结果：退出码 1；14 项中 4 项失败。首因是根 Suite 未包含 `known_acceptance`；其余为版本仍为 0.12.1、eval 未接入安装/检查、三类循环终止契约缺失。

## 自审记录

- PRD 5 条功能均有确定性测试或 doctor；包含正常、边界和缺失资源异常场景。
- 验收标准覆盖数：5/5；接口覆盖数：不适用。
- 问题数：0；自动修复：0；需人工确认：0。
