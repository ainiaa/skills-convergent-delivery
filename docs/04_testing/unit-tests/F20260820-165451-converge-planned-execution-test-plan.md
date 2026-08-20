<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-165451 -->
<!-- 功能名称: converge-planned-execution -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260820-165451-converge-planned-execution-arch.md -->

# 测试计划：Converge 计划化执行

| 验收项 | 正常场景 | 边界/异常场景 | 自动化测试 |
|---|---|---|---|
| F-01/F-08 | 四 Skill 安装、卸载、版本一致 | 残缺安装被 doctor 识别 | `scripts/test_install.py` |
| F-02 | PDLC 单个 `pdlc-run` 使用 fresh | 多任务拆解 PDLC 被拒绝 | `test_plan_check.py` |
| F-03/F-04 | 依赖形成 wave、独立路径可并行 | 循环、未知依赖、重复 ID、路径重叠 | `test_plan_check.py` |
| F-05/F-06 | 决策和无响应协议可发现 | 运行进程不误中断、最多恢复一次 | `test_skill_contracts.py` |
| F-07 | 新鲜证据得到 DONE | 陈旧证据降为 PARTIAL，变更目标与范围漂移可见 | `test_plan_check.py` |

红灯预期：`converge-plan`、`plan_check.py` 和执行控制协议尚不存在，新增测试失败。实现后运行 `bash scripts/check.sh`，所有检查退出码须为 0。

## 自审记录

- PRD 验收覆盖：8/8。
- 正常、边界、异常和恢复场景：4/4 通过设计检查。
- 测试沿用现有 `unittest` 与 `scripts/check.sh`，未引入新框架。
