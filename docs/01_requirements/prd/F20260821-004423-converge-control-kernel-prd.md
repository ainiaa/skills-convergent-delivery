<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-004423 -->
<!-- 功能名称: converge-control-kernel -->
<!-- 阶段: 需求 -->
<!-- 前置文档: docs/06_tasks/F20260821-converge-control-kernel-plan.json -->
<!-- 创建时间: 2026-08-21T00:44:23+08:00 -->

# PRD：Converge Control Kernel

## 1. 背景与目标

### 1.1 背景

Converge 已具备 Provider Binding、worker registry、进度快照和确定性回执，但绑定尚未完整覆盖真实入口与任务契约，宿主能力仍主要依赖文字约定，自修改时控制器身份又绑定活动源码，无法稳定恢复当前任务。

### 1.2 目标

- 冻结 Provider manifest、实际入口、来源闭包和任务契约，任一变化都明确阻塞恢复。
- 提供稳定 auto 和显式 Provider ID 选择，PDLC 不可用时 Native 独立闭环。
- 统一 Codex、Claude Code、单上下文 Runtime Adapter 的能力协商与 worker 生命周期语义。
- 由父控制器根据宿主查询生成 heartbeat；worker 只上报客观 milestone；进度去重且不展示百分比或 ETA。
- 启动时冻结 Controller Snapshot，使 Converge 修改自身时当前任务仍由原快照控制。
- 默认输出面向用户的分层报告，异常或显式请求才展示技术诊断。

## 2. 目标用户

| 用户角色 | 描述 | 核心需求 |
|---|---|---|
| Converge 使用者 | 在 Codex、Claude Code 或单上下文中运行交付任务 | 可信、可恢复、无伪能力的闭环 |
| 控制器维护者 | 修改 Provider、Runtime 或 Converge 自身 | 变化可检测且当前任务不被自修改破坏 |
| 交付负责人 | 阅读进度与最终结果 | 简洁、去重、面向结果的状态视图 |

## 3. 功能需求

### 3.1 功能列表

| 编号 | 功能 | 优先级 | 描述 | 验收标准 |
|---|---|---|---|---|
| FR-1 | 完整 Provider Binding | P0 | 共享 Provider Contract 冻结 manifest、入口、闭包和 task contract | 任一冻结来源变化时恢复校验失败 |
| FR-2 | 精确 Provider 选择 | P0 | auto 顺序稳定，并支持显式 Provider ID | 相同能力集合选择结果固定；显式不可用时阻塞 |
| FR-3 | Runtime 能力协商 | P0 | Codex、Claude Code、单上下文统一描述 dispatch/query/wait/interrupt | 仅暴露宿主真实支持的动作，不足时返回 manual handoff |
| FR-4 | worker 观察语义 | P0 | query/wait/interrupt 只作用于当前 run 的精确 ref | 未登记、非 owner 或不支持的操作明确拒绝 |
| FR-5 | 父控制器进度 | P0 | worker milestone 与父查询 heartbeat 分离并去重展示 | heartbeat 不增加 objective revision；重复状态不重复展示 |
| FR-6 | Controller Snapshot | P0 | 启动时复制控制文件到控制状态根并冻结身份 | 目标工作区修改控制源码后，当前任务仍使用快照校验 |
| FR-7 | 分层报告 | P1 | summary 默认面向用户，diagnostic 按需展示 | 默认无内部状态噪声；异常或 detail 才有诊断层 |
| FR-8 | 契约同步 | P1 | README、CHANGELOG、VERSION、Skill 和引用文档一致 | 契约检查、doctor 和全量测试通过 |

### 3.2 用户故事

1. 作为执行者，我希望 Provider 来源完整冻结，以便恢复时不会悄悄切换实现。
2. 作为宿主集成者，我希望先协商能力，以便不能 query/wait/interrupt 时明确降级而不是伪造成功。
3. 作为用户，我希望只看到去重的客观进度，以便知道任务仍在运行且不被虚假百分比误导。
4. 作为 Converge 维护者，我希望自修改不改变当前控制程序，以便当前交付仍可恢复和审计。
5. 作为交付负责人，我希望默认报告聚焦结果，以便必要时再展开技术诊断。

### 3.3 核心用例

- Provider 首次选择后生成完整 Binding；恢复时逐项核验。
- 父控制器协商宿主能力、登记稳定 worker ref，并用 query/wait 观察精确 worker。
- 长命令运行时，父控制器基于宿主查询写入 heartbeat；worker 仅发送新客观里程碑。
- 启动任务时生成不可变快照；目标 workspace 可修改 Suite，但当前状态仍引用快照。
- 完成时生成 summary；仅异常或 detail 请求附 diagnostic。

## 4. 验收标准

1. 修改 manifest、task contract、实际入口或 closure 任一项，冻结 Binding 校验均返回非零并说明变化来源。
2. auto 在 PDLC、适配 TDD、Native 间按固定优先级选择；`--provider <id>` 精确选择或非零阻塞。
3. 三类 Runtime profile 均返回结构化 capabilities；不支持 query 的 profile 不允许自动 dispatch/resume/interrupt。
4. query/wait/interrupt 必须携带当前 run 已登记的精确 worker ref；不支持的动作返回明确降级。
5. 父查询 heartbeat 不增加客观 revision；相同状态视图只输出一次；不包含 `%`、ETA 或剩余时间估计。
6. 快照创建后修改目标 workspace 的控制文件，使用快照进行 controller 校验仍成功；篡改快照则失败。
7. 默认报告只含结果、关键变化、验证和过程；异常或 `--detail` 才展示技术诊断。
8. `bash scripts/check.sh`、`bash install.sh --doctor --target codex --offline`、`git diff --check` 全部通过。

## 5. 非功能需求

- 仅使用 Python 标准库和现有模块；不引入 daemon、RPC、任意 manifest command 或无限事件日志。
- 状态写入保持 0600、原子替换与单 writer 约束。
- 所有错误为确定性、可测试的显式结果；不把自然语言 receipt 当宿主终态。

## 6. 不在范围内

- 后台 daemon、跨机器调度、通用 RPC、任意 Provider 命令执行。
- 无限事件历史或共享工作区并行写。
- commit、tag、push、publish、install 和 `pdlc-ship`。

## 7. 依赖与约束

- 扩展 F20260820-215348 的 Runtime vNext 状态、Binding、worker 与报告能力。
- 仅修改冻结计划 T1 的 `owned_paths`；`planned_task=true`，不再拆分或委托。

## 8. 自审记录

- 审查时间：2026-08-21T00:44:23+08:00
- 完整性：8/8 章节通过；5 条用户故事，8 条可执行验收标准。
- 一致性：8 个功能项均由验收标准覆盖。
- 修复：将“稳定”“友好”等表述改写为固定优先级、非零结果、去重输出等可测试行为。

---
创建日期：2026-08-21  
作者：Jeff.Liu  
状态：已评审
