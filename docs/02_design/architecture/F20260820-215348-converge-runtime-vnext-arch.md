<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-215348 -->
<!-- 功能名称: converge-runtime-vnext -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260820-215348-converge-runtime-vnext-prd.md -->
<!-- 创建时间: 2026-08-20T21:57:00+08:00 -->

# Converge Runtime vNext 架构设计

## 1. 最小变更面

- `delivery_state.py` / `delivery_next.py`：Schema v6，新增冻结 `controller` 和当前 run 的 `workers`；v5 首次写入只添加这两项后原子迁移。
- `delivery_engine.py`：读取 Suite 自带的 `providers/pdlc-v1.json` adapter manifest；支持 feature/fix/refactor；fingerprint 覆盖 manifest 声明的真实入口和闭包。
- `delivery_report.py`：把输入读取改为 `--state` 与 `--input -` 互斥二选一，报告生成逻辑不变。
- `scripts/check.sh`：调用四个 Skill 的官方 `quick_validate.py`；开发依赖采用仓库级锁定声明，缺失时明确失败。
- `references/execution-control.md`：worker/watchdog 唯一规则源；其他入口只保留摘要链接。

## 2. Schema v6

```json
{
  "schema_version": 6,
  "controller": {"version": "0.10.0", "fingerprint": "sha256"},
  "workers": [
    {"ref": "stable-host-ref", "role": "pdlc", "owner_run_id": "run-id", "status": "working"}
  ]
}
```

`controller` 对当前 Suite 的 `VERSION`、主 Skill、执行控制规范以及 state/next/engine helper 计算稳定摘要。恢复时 version 或 fingerprint 不同即阻塞。worker ref 唯一，role/owner 不可变，状态只允许 `working → completed|interrupted|blocked`；所有项都必须属于 state 的当前 `run_id`。进入 `complete` 前 registry 必须全部为宿主终态。

旧 v5 在 `delivery_state.py write` 内迁移：先完整验证 v5，再只添加当前 controller、空 workers 并改为 v6；若磁盘中是 v5，候选除这三项及正常 revision/协议推进外不得借迁移改写冻结字段或 ledger。

## 3. Provider adapter manifest

Suite 自带 `providers/pdlc-v1.json`，字段为 `schema_version/provider_id/provider_version/task_contracts/authorization`。每个 task kind 声明实际 `entrypoint`、显式 `closure` 和适配版本的 `source_fingerprint`。路径只允许 provider root 内相对路径；解析支持源码树的 `skills/<name>` 与已安装的 `<name>` 两种布局。

授权边界要求 manifest 明确：可执行 task kind、必须停止的业务/公共契约/权限/发布/不可逆决策，以及禁止 `pdlc-ship/commit/tag/push/publish/install`。缺 manifest、缺字段、source fingerprint 不匹配或 task kind 未授权时返回 `incompatible`；发现 PDLC root 但未适配时 auto 模式也 blocked，不降级为 absent/native。

Engine 选择结果冻结 `provider_id/provider_version/provider_manifest/provider_fingerprint/provider_source_fingerprint/pdlc_entrypoint`。恢复同时核验 manifest 和源码闭包，因此入口、传递依赖、版本或来源变化均阻塞。

`refactor` 直接映射 `pdlc-refactor`，并把 `preserve_external_behavior=true` 写入选择结果/委托契约；feature/fix 不改变入口语义。

## 4. 委托与控制边界

Converge 仍是 owner。Provider capsule 只授权已冻结范围内的需求、设计、TDD、实现和评审；遇到业务规则、公共契约、权限、发布或不可逆事项必须停止。Provider 的自行假设或自动发布文本不提升权限。worker/watchdog 的完整规则只维护在 `references/execution-control.md`。

## 5. 报告与校验

`--input -` 直接读取一个已验证 Schema v6 JSON，不触发 state path、lease 或写入；`--state` 保持兼容。两条路径共用 `build_report`，同输入逐字确定。

正式检查用环境变量或已知系统 Skill 路径定位官方 `quick_validate.py`，对 `converge`、`converge-plan`、`converge-review`、`converge-batch` 各执行一次。仓库声明精确开发依赖；缺失 PyYAML 或 validator 时 check 非零并给出复现命令，不静默跳过或全局安装。

## 6. 安全与兼容性

- 无新运行时依赖；JSON、hash、path、argparse 均用标准库。
- 保留 lease/CAS/私有临时文件/fsync/原子替换。
- Batch Protocol 不变。
- 所有错误在 stdout/stderr 中区分 absent、incompatible、authorization 和 drift。

## 7. 自审记录

PRD 的 7 项功能均有落点；状态迁移、入口闭包、授权边界、refactor 外部行为契约、stdin 与 validator 失败语义已覆盖。问题数 0，修复数 0。
