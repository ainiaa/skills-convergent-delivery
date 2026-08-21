<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-102230 -->
<!-- 功能名称: plan-granularity -->
<!-- 阶段: 需求 -->
<!-- 前置文档: docs/06_tasks/F20260821-converge-013-review-loop-plan.json -->
<!-- 创建时间: 2026-08-21T10:22:30+08:00 -->

# PRD：计划粒度与执行连续性

## 1. 背景与目标

### 1.1 背景

Plan Contract 目前只以自由文本约定“一个 task 一个结果”，helper 无法机械区分垂直切片、宽重构和最终集成，也无法阻止长上下文把多个独立结果包装成一个宽泛 task。另一方面，所有多任务计划都被标记为 `batch`，导致旧 Batch 协议在同一会话顺序执行前错误要求本地 commit 授权。

### 1.2 目标

- 将任务类型和单结果边界纳入机器可校验的计划契约。
- 对长上下文中的宽泛单任务给出结构化、可操作的阻塞原因。
- 保持真正单结果任务和有依赖多任务可执行。
- 区分同会话顺序执行与跨会话 Batch checkpoint；仅后者需要请求本地 commit 授权。

## 2. 目标用户

| 用户角色 | 描述 | 核心需求 |
|---|---|---|
| 计划编写者 | 把复杂需求转成 Plan Contract | 明确任务粒度，错误可立即修正 |
| Converge 控制器 | 选择 current、fresh、sequential 或 batch | 不因多任务而误触 commit 门禁 |
| Batch 执行者 | 跨会话恢复计划 | checkpoint 前获得明确的本地 commit 授权 |

## 3. 功能需求

### 3.1 功能列表

| 编号 | 功能 | 优先级 | 描述 | 验收标准 |
|---|---|---|---|---|
| FR-1 | 任务类型 | P0 | task 显式区分 `vertical_slice`、`wide_refactor`、`integration` | 三种类型均能被确定性校验 |
| FR-2 | 单结果边界 | P0 | task 以结构化 `outcomes` 声明结果 | 每个 task 恰好一个 outcome；多个时阻塞并提示拆分 |
| FR-3 | 长上下文旧计划门禁 | P0 | 无显式粒度的长上下文单任务不能被自动推断 | 返回非零及可操作的迁移/拆分原因 |
| FR-4 | 兼容执行 | P0 | 显式单结果和有依赖多任务继续通过 | 单任务为 fresh/current，多任务形成正确 waves |
| FR-5 | 连续性选择 | P0 | 计划声明同会话或跨会话 checkpoint | 同会话多任务为 sequential；跨会话才为 batch |
| FR-6 | commit 门禁语义 | P0 | helper 明确输出是否需要 commit 授权 | 仅 cross-session batch 输出 `commit_authorization_required=true` |
| FR-7 | 契约文档同步 | P1 | Skill 与 Plan Contract 描述相同字段和行为 | 文档契约与测试一致 |

### 3.2 用户故事

1. 作为计划编写者，我希望每个任务显式声明类型和唯一结果，以便粒度问题在执行前被发现。
2. 作为复杂需求执行者，我希望多个独立结果必须拆成垂直切片，以便每个切片可独立验收。
3. 作为重构维护者，我希望宽重构可以被明确标注，以便它不被误认成多个业务结果。
4. 作为集成负责人，我希望最终集成任务有依赖，以便它只在前置切片完成后运行。
5. 作为同会话执行者，我希望顺序任务不要求 commit，以便不扩大用户授权。
6. 作为跨会话 Batch 执行者，我希望 checkpoint 明确触发 commit 授权，以便恢复基线可信。

### 3.3 核心用例

- 新计划使用 schema v3，为每个 task 声明 `task_kind` 和唯一 `outcomes`。
- 长上下文 schema v1/v2 单任务因无法证明粒度而被阻塞，提示升级 schema 或拆分任务。
- 多个有依赖的任务通过校验并按依赖形成 waves。
- 同会话多任务返回 `sequential`，不请求 commit；显式 cross-session checkpoint 返回 `batch` 并请求一次本地 commit 授权。

## 4. 验收标准

1. `vertical_slice`、`wide_refactor`、`integration` 三种任务类型各有通过用例；未知类型返回非零。
2. long context task 的 `outcomes` 含两个独立结果时返回非零，错误包含 task id、拆分动作和允许类型。
3. schema v3 的 long context 单 outcome 垂直切片通过；有依赖多任务通过并形成预期 waves。
4. integration task 无依赖时返回非零，有依赖时通过。
5. 同会话多任务输出 `execution_mode=sequential` 和 `commit_authorization_required=false`。
6. 仅 `checkpoint=cross_session` 输出 `execution_mode=batch` 和 `commit_authorization_required=true`。
7. `PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-plan/scripts/test_plan_check.py` 与 `git diff --check` 通过。

## 5. 非功能需求

- 只使用 Python 标准库和现有文件，不增加依赖。
- 校验错误必须确定、简短、可操作；不以自然语言启发式猜测 task goal。
- 旧 schema 的短单任务和多任务可安全迁移；无法证明粒度的 long 单任务必须停止。

## 6. 不在范围内

- 修改 Batch state helper 或实际创建 commit。
- 自动分析自然语言并猜测独立结果数量。
- 并行写工作区、发布、tag、push、install 或 `pdlc-ship`。
- 修改冻结计划 `docs/06_tasks/F20260821-converge-013-review-loop-plan.json`。

## 7. 依赖与约束

- 本任务是 `plan-converge-013-review-loop-20260821/T1`，`planned_task=true`，不递归规划、不派发子代理。
- 仅修改 `skills/converge-plan`、`docs`、`CHANGELOG.md`。
- 跨会话 commit 授权仍由 Batch 控制器执行；本任务只修正计划层路由与契约。

## 8. 自审记录

- 审查时间：2026-08-21T10:22:30+08:00
- 完整性：8/8 章节通过；6 条用户故事、7 条可执行验收标准。
- 一致性：7 个功能项均由验收标准覆盖。
- 可操作性：用明确字段、退出码和输出值替换“合理粒度”“必要时”等模糊表述。
- 一次复查：0 个未解决问题。

---
创建日期：2026-08-21  
作者：Jeff.Liu  
状态：已评审
