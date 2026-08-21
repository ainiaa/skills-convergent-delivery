<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-004423 -->
<!-- 功能名称: converge-control-kernel -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260821-004423-converge-control-kernel-arch.md -->

# Converge Control Kernel 测试计划

## 测试矩阵

| 验收 | 正常 | 边界 | 异常 | 测试文件 |
|---|---|---|---|---|
| 完整 Binding | manifest/contract/入口/closure 均冻结 | stage candidate、Native 入口 | 换成无关文件、删除 stage source、任一来源修改拒绝 | `scripts/test_provider_contract.py`、`test_delivery_engine.py`、`test_delivery_next.py` |
| 稳定/显式选择 | auto 固定顺序、显式 ID | 仅 Native | ID 不存在、显式能力缺失 | `scripts/test_delivery_engine.py` |
| Runtime 协商 | Codex/Claude 完整能力 | 可选 wait/interrupt | 无 query 降级、非 owner 拒绝 | `scripts/test_runtime_adapter.py` |
| worker 观察 | query/wait 状态规范化 | timeout 保持 working | 未知状态、unsupported interrupt | `scripts/test_runtime_adapter.py` |
| 进度语义 | milestone + parent heartbeat | 首次 heartbeat、重复视图 | worker heartbeat、未知 ref | `scripts/test_delivery_progress.py`、`test_delivery_state.py` |
| Snapshot | 完整资源闭包；快照内 resolver auto→Native | 同 hash 复用、空 HOME | 可写 workspace 伪装、provenance/隔离错误、篡改 | `scripts/test_controller_snapshot.py` |
| 分层报告 | 默认 summary、detail diagnostic | 无下一步 | blocked 自动诊断 | `scripts/test_delivery_report.py` |
| 契约同步 | Skill/README/VERSION/doctor | offline doctor | 缺文件安装检查 | `test_skill_contracts.py`、`test_install.py` |

## 红灯证据

2026-08-21 执行五组目标测试，退出码均为 1：

- `test_provider_contract.py`：缺少 `provider_contract.py`。
- `test_runtime_adapter.py`：缺少 `runtime_adapter.py`。
- `test_controller_snapshot.py`：缺少 `controller_snapshot.py`。
- `test_delivery_progress.py`：缺少 parent observation、worker milestone 与去重视图。
- `test_delivery_report.py`：`--detail` 未实现，诊断层为空。

## 自审记录

- 验收标准覆盖：8/8。
- 场景：正常、边界、异常均有；无鉴权 API，不虚构 401/403/404/409。
- 幂等性：snapshot 同 hash 复用、status 重复指纹不输出。
- 测试质量：通过公共函数/CLI 断言可观察行为，不断言内部实现细节。
- 未解决问题：0。
