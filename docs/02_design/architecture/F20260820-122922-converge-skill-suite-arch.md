<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-122922 -->
<!-- 功能名称: converge-skill-suite -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260820-122922-converge-skill-suite-prd.md -->
<!-- 创建时间: 2026-08-20T04:31:13Z -->

# 架构设计：Converge Skill Suite

## 1. 目标与非目标

### 1.1 目标

- 用三个互斥入口隔离单任务执行、只读审查和多 Batch 调度。
- 用确定性协议连接角色，避免调度器解析自然语言报告。
- 复用现有 engine、lease、state 和 installer 模式，不引入依赖。
- 让简单任务只加载 `converge`，高级资料按需披露。

### 1.2 非目标

- 不实现后台服务、消息队列或通用插件框架。
- 不把 PDLC/TDD/验证拆成更多用户 Skill。
- 不自动执行 push、merge、release 或破坏性回滚。

## 2. Suite 结构

```text
仓库根目录（converge）
├── SKILL.md
├── scripts/                     单任务 engine/lease/state helper
├── references/                  单任务按需规则
└── skills/
    ├── converge-review/
    │   ├── SKILL.md
    │   ├── agents/openai.yaml
    │   └── references/review-contract.md
    └── converge-batch/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/batch-contract.md
        └── scripts/batch_state.py
```

根目录继续作为 `converge` 的安装源，避免迁移现有脚本和状态路径。两个新 Skill 各自自包含其必要说明；`converge-batch` 仅通过已安装的 sibling `converge` 调用执行能力。

## 3. 职责与触发

| Skill | 触发 | 写权限 | 依赖 |
|---|---|---|---|
| converge | 实现、修复、重构一个明确代码任务 | 当前任务 owned diff | PDLC/TDD 可选 |
| converge-review | 只读检查代码、diff 或委托独立审查 | 无 | 无；可被 converge 委托 |
| converge-batch | 按已有多 Batch 计划持续调度 | 仅调度状态 | converge 必需，宿主任務能力可选 |

三个 frontmatter 不使用完整流程摘要，只描述能力、触发和必要排除，降低误路由。

## 4. 单任务执行流程

```text
scope
→ verification-profile
→ PDLC / adapted TDD / native
→ semantic-review
→ optional independent-review
→ finding-closure
→ verify-final
→ receipt + user-report
```

- PDLC 已完成阶段 review 时，将其视为意图审查，不重复执行同类审查。
- 风险触发器或影响面扩大时，才委托全新上下文加载 `converge-review`。
- reviewer 修复后的“再审查”默认只关闭原发现；仅影响面扩大时允许一次新的风险审查。
- 任何审查结果都绑定 `baseline`、`diff_fingerprint` 或 `tree_hash`；无关生产代码变化后不得继续引用为新鲜结论。

## 5. Review Protocol v1

### 5.1 请求

```json
{
  "protocol_version": 1,
  "mode": "intent | blind",
  "acceptance": ["..."],
  "scope": ["..."],
  "baseline": "<commit>",
  "source_fingerprint": "<sha256>",
  "evidence": [{"check": "...", "result": "pass|fail|unknown"}]
}
```

`blind` 模式不得传入实现者的理由和完整对话；`intent` 模式可传已冻结设计决策。

### 5.2 结果

```json
{
  "protocol_version": 1,
  "source_fingerprint": "<sha256>",
  "independent": true,
  "findings": [
    {
      "fingerprint": "<stable-id>",
      "evidence": "<location/reproduction>",
      "impact": "<user effect>",
      "root_cause": "<cause>",
      "scope": "current|pre-existing|out-of-scope"
    }
  ]
}
```

reviewer 只返回发现，不修改代码、不决定发布、不扩充验收范围。宿主不能提供全新 Agent 时 `independent=false`，用户回执不得声称完成独立审查。

## 6. Batch Protocol v1

### 6.1 全量预检

开始前一次性验证所有 Batch 是否有：目标、范围、输入/输出接口、前置提交、验收证据、实际验证方式和最终集成检查。缺少项统一阻塞，不在运行数小时后逐批询问。

### 6.2 上下文胶囊

执行者只接收当前 Batch 的全局约束、目标、范围、消费/产出接口、基线、验收和验证命令。调度器只能从已冻结计划复制整理，不能阅读业务代码或补技术方案。

### 6.3 状态机

```text
pending → dispatching → running → validating-receipt → completed
                                      └──────────────→ blocked

计划级：active ↔ paused → completed | blocked | stopped
```

- `dispatch_id` 在派发前生成且不可改变；不确定是否已派发时阻塞，不自动重派。
- `plan_fingerprint` 和 Batch 顺序在 init 后不可修改。
- 只有当前 Batch 完成后才能推进下一批；一个计划使用一个专用 worktree。
- `pause` 不派发下一批；`stop` 保留已有提交和状态。

### 6.4 Batch receipt

receipt 绑定 `batch_id`、`dispatch_id`、`commit_id/tree_hash`、验收证据和未解决问题。源码树与验证证据不一致时拒绝完成。

所有 Batch 完成后，计划级最终验收必须有通过证据；失败时进入 blocked，由用户或规划流程新增明确修复 Batch，调度器不得自行改代码。

## 7. 安装与版本

- 根 `VERSION` 是 Suite 唯一版本。
- installer 对一个 runtime 先预检三个目标，再逐个建立临时链接并原子替换；任何冲突都在修改前失败。
- Codex 安装到 `~/.codex/skills/{converge,converge-review,converge-batch}`，Claude Code 对应 `~/.claude/skills/`。
- 卸载仅移除能识别为当前 Suite 的链接。
- 单任务 Schema v5 保持不变；Batch 使用独立 Schema v1，不将旧 state 静默迁移。

## 8. 测试设计

1. 安装测试：两个 runtime、三个入口、冲突预检、卸载和版本。
2. Batch helper：初始化、合法推进、非法跳转、陈旧 revision、计划漂移、重复 dispatch、receipt 不匹配、缺少最终验收。
3. 静态边界：三个 frontmatter 唯一、review 明确只读、batch 明确不读代码、root 不再定义 plan/review 模式。
4. 回归：现有 engine、lease、state、reporting 测试全部通过。
5. 前向场景：PDLC 去重、独立审查降级、Batch 中断恢复和多窗口重复派发。

## 9. 风险与决策

| 风险 | 决策 |
|---|---|
| 拆分导致三个版本不一致 | 一个 installer 和一个 VERSION，安装前全量预检 |
| reviewer 继承实现偏见 | `blind` 仅传最小材料，并记录 `independent` |
| 调度器重复派发 | 不可变 dispatch ID、revision CAS、无法确认即阻塞 |
| 规则增多导致 token 上升 | 根 Skill 精简，review/batch 仅按需加载 |
| 过度工程化 | 不新增后台进程、框架或第四个用户 Skill |

## 10. 自审记录

- PRD P0/P1 覆盖：6/6。
- 触发、状态、安装、兼容和测试边界均有对应设计。
- 未新增外部依赖；现有脚本保持原职责。
- 评审结论：通过。

---
作者：Jeff.Liu
状态：已评审
