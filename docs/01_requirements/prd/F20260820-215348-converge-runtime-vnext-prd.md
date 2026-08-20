<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-215348 -->
<!-- 功能名称: converge-runtime-vnext -->
<!-- 阶段: 需求 -->
<!-- 前置文档: 无 -->
<!-- 创建时间: 2026-08-20T21:55:00+08:00 -->

# Converge Runtime vNext PRD

## 1. 背景

当前单任务 Schema v5 没有持久化 run-scoped worker，也没有冻结 Converge controller；PDLC 能力探测只检查若干 `SKILL.md`，无法表达版本、入口、授权边界和传递依赖。报告器又强制依赖持久 state，使简单任务承担不必要的 lease 成本。

## 2. 目标用户与目标

目标用户是使用 Converge 执行单任务、PDLC feature/fix/refactor 或维护 Suite 的工程师。目标是：恢复时可证明 controller/provider 未漂移；complete 前所有本轮 worker 已进入宿主终态；PDLC refactor 可正确路由；简单任务可直接从 stdin 生成确定性报告；正式检查真实覆盖四个 Skill 的官方校验。

## 3. 用户故事

1. 作为任务 owner，我希望本轮 worker 的 ref、角色、owner 和宿主状态被持久化，并在 complete 前形成屏障。
2. 作为恢复任务的执行者，我希望 controller 或 provider 来源变化被明确阻塞，而不是静默换源或降级。
3. 作为重构任务用户，我希望 `refactor` 路由到 `pdlc-refactor`，且契约强制外部行为不变。
4. 作为简单任务用户，我希望把内存中的已验证结果经 stdin 交给报告器，不创建 state 或 lease。
5. 作为维护者，我希望正式检查可复现地运行四个 Skill 的官方 validator，缺少 validator 依赖时不能伪报完整通过。

## 4. 功能清单

| 优先级 | 功能 | 验收摘要 |
|---|---|---|
| P0 | 单任务 Schema 升级与 v5 迁移 | 只添加 controller/workers；非宿主终态拒绝 complete；只管理当前 run |
| P0 | Provider adapter manifest | 校验 id/version/entrypoint/task kind/授权边界，冻结来源及传递依赖 |
| P0 | PDLC refactor | `refactor` 映射 `pdlc-refactor`，feature/fix 保持兼容 |
| P0 | 委托边界 | 业务规则、公共契约、权限、发布、不可逆事项停止；禁止 ship/commit/tag/push/publish/install |
| P0 | stdin 报告 | `delivery_report.py --input -` 确定性输出，`--state` 继续可用 |
| P0 | 行为测试与正式检查 | 覆盖七类关键行为；四个 Skill quick_validate 不静默跳过 |
| P1 | 文档去重 | `references/execution-control.md` 为 worker/watchdog 唯一真源，其他位置只摘要链接 |

## 5. 验收标准

1. Schema v5 可在一次写入中安全迁移到新 schema，迁移只添加冻结 controller 与空 worker registry；新状态必须使用新 schema。
2. 任一当前 run worker 的宿主状态不是 `completed|interrupted|blocked` 时，候选 `status=complete` 被 helper 拒绝；其他 run 的 worker 不受管理。
3. 恢复时 controller version/fingerprint 或 provider manifest、入口、闭包 fingerprint 任一变化均返回明确 blocked/incompatible 原因。
4. `delivery_engine.py --kind refactor` 在兼容 PDLC 上选择 `pdlc-v1` 且入口为 `pdlc-refactor`；feature/fix 既有测试继续通过。
5. Provider manifest 缺字段、未授权 task kind/边界或安装版本未适配时明确阻塞；不静默视为不存在。
6. 委托 capsule 明确停止点，并禁止 `pdlc-ship`、commit、tag、push、publish、install。
7. `delivery_report.py --input -` 与同内容的 `--state` 产生相同报告；两者互斥且至少提供一个。
8. 行为测试覆盖 worker 屏障、v5 迁移、controller/provider 漂移、refactor 路由、传递依赖 fingerprint、stdin report、未适配 provider 阻塞。
9. `scripts/check.sh` 在仓库内隔离开发环境运行四个 Skill 的官方 quick_validate；依赖不可用时失败并说明，不全局安装。
10. `scripts/check.sh`、offline doctor、`git diff --check` 全部成功，VERSION 按兼容性升级为 0.10.0。

## 6. 非功能要求

- 仅使用 Python 标准库和最小 JSON manifest，不增加运行时依赖。
- 所有状态写入继续使用 lease、CAS、私有临时文件和原子替换。
- 错误原因稳定、明确，可区分 absent、incompatible、drift 和 authorization blocked。
- 保留自动触发，不修改用户配置，不删除用户文件。

### 6.1 关系

| 类型 | 功能 |
|---|---|
| extends | F20260820-165451 |

## 7. 不在范围内

- Batch Protocol 扩展（除非读取新单任务状态所必需）。
- 自动发布、提交、tag、push、publish、install 或修改用户配置。
- 新中间件、新运行时框架或全局依赖安装。

## 8. 自审记录

- 时间：2026-08-20T21:55:00+08:00
- 完整性：背景、用户、5 条用户故事、7 项功能、10 条可执行验收、非功能和排除项齐全。
- 一致性：所有 P0 功能均有对应验收；无模糊的“尽量/适当”表述。
- 问题数：0；修复数：0。
