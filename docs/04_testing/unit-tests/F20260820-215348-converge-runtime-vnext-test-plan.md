<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-215348 -->
<!-- 功能名称: converge-runtime-vnext -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260820-215348-converge-runtime-vnext-arch.md -->
<!-- 创建时间: 2026-08-20T21:59:00+08:00 -->

# Converge Runtime vNext 测试计划

| 验收 | 行为测试 | 场景 |
|---|---|---|
| Schema v5→v6 | `test_v5_write_migrates_only_controller_and_empty_worker_registry` | 正常迁移/只添加字段 |
| Schema v5 迁移边界 | `test_v5_migration_rejects_stage_or_ledger_changes` | 拒绝迁移时夹带阶段和证据变更 |
| worker 完成屏障 | `test_complete_rejects_a_current_run_worker_without_host_terminal_status` | working worker 异常完成 |
| controller 漂移 | `test_controller_drift_is_rejected_after_it_is_frozen` | fingerprint 篡改 |
| refactor 路由 | `test_refactor_routes_to_pdlc_refactor_with_external_behavior_contract` | 正常路由/行为不变标记 |
| 传递依赖漂移 | `test_transitive_dependency_change_blocks_a_frozen_pdlc_provider` | closure 文件变化 |
| 未适配 provider | `test_installed_but_unadapted_pdlc_is_explicitly_blocked` | 已安装但无兼容 manifest |
| stdin report | `test_stdin_input_matches_state_file_without_a_lease` | stdin 与 state 等价且无需 lease |
| 官方 validator | `test_check.py` + 正式 `scripts/check.sh` | 四个 Skill 均执行；缺依赖失败 |

## 红灯证据

2026-08-20T21:59:00+08:00 运行三个定向测试文件：42 个测试中 36 个通过，5 个失败、1 个错误。失败明确来自旧实现缺少 refactor、manifest 不兼容阻塞、Schema v6 迁移、worker 屏障、controller 冻结和 stdin 输入。传递依赖既有 fingerprint 行为已通过，后续改为 manifest 闭包后继续作为回归。

## 自审记录

10 条 PRD 验收均映射到行为测试或正式命令；覆盖正常、边界、异常、非法状态和兼容路径。验收覆盖 10/10，CLI 覆盖 engine/state/report/check 4/4。独立 blind review 发现并关闭 1 个迁移边界缺陷。
