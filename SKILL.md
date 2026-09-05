---
name: converge
description: "Implement/fix/refactor authorized work: 实现/修复/重构/按方案修改/修复已知问题/闭环完成. Excludes read-only review, autonomous continuation, multi-model execution, and multi-Batch."
metadata:
  compatibility: Requires Git and Python 3.9+; full-closure audits require CodeGraph. Install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge：单任务闭环执行

Converge 始终是 controller；规划/只读用 `converge-plan`、`converge-review`；见 `references/activation.md`。

需要持久状态的显式闭环使用 arm v11；终态只认新鲜证据。简单 `inline` 不创建 run。显式闭环先 arm 当前 workspace 的唯一 active run；active run 未到 `complete|blocked` 时不得输出 final。

用户要求“逐步修复 / 分步执行 / 按计划一步步做”时，按 [分步可见交付](references/execution-control.md#分步可见交付) 先探测当前原生计划工具：可用则调用并核对成功回执；不可用或同步失败则明确说明降级，逐项显示文字清单。文字分步不依赖原生计划面板。计划文件、投影 JSON 和文字汇报不代表原生面板已显示。每步开始和结束都必须各用一条独立的 commentary 消息：开始说明步骤编号、目标和范围，结束展示实际改动、验证和状态；结束消息不得与下一步的开始合并，再进入下一步。

## 开始

Skill 根目录记为 `CONVERGE_SKILL_DIR`。冻结验收、路径和基线，仅改 task diff；不可逆问用户。模型自述不放行；验收实检，`unknown` 失败，走完整路径。

验证纪律：沿用项目已有的检查命令并保存实际 argv、退出码和当前源码回执；命令不存在、超时或无权限时标为 `uncovered`，不得以替换、删除或放松检查命令取得通过。仅当任务明确包含用户流程时，才将 P0 用户流程列为验收项；每项必须关联实际 E2E 标识和本次运行回执，否则保持 `uncovered`。

TDD 覆盖：涉及运行时行为的功能或修复，先将每条验收项至少映射一个测试，再改生产代码；测试至少覆盖正常、边界和异常场景，权限、并发或幂等风险按任务语义加入。测试优先覆盖公共 seam，每个测试只验证一个可观察行为；mock 只用于外部系统边界，不验证内部调用顺序。先按实际调用链列出入口、调用方、共享副作用或外部契约等影响链，并把每条链绑定到本次回归测试。红灯与绿灯回执必须是由 `evidence_contract.py run` 产生的 observed Evidence Receipt；每个测试须给出出现在红绿 `argv` 中的精确 `selector`，pytest、Gradle、Maven、Vitest/Jest 等已知 runner 必须使用其 runner selector 语法。红灯还必须声明 `failure_class` 为 `missing_behavior|assertion`；编译、Mock 或环境错误不能当作有效红灯。每个绿灯须有一次稳定性 rerun；可用时 CodeGraph receipt 绑定最终影响链，不可用时图谱范围保持 `uncovered`；金额、支付、权限、安全、事务、并发、幂等、数据访问和契约风险还须有 mutation 检查的 integration/contract 测试。原生 `native-v1` 的 coverage 项目配置优先：先用 `python3 "$CONVERGE_SKILL_DIR/scripts/native_tdd_policy.py" resolve --workspace <workspace>` 解析，`test-commands.yml` 的安全 coverage argv 优先；pytest 和 Vitest 会注入 `quality-targets.yml` 或默认 >=85% 的阈值，Maven/Gradle 仅在已运行 JaCoCo gate 且项目阈值足够时放行，其余命令保持 `uncovered`。没有可执行 coverage 工具时保持 `uncovered`。最终将验收、测试标识、selector、场景、红绿回执、冻结 `risk_flags`、mutation 与影响链按 [TDD 追溯](references/tdd-providers.md#tddimpact-trace-v4) 输入 `python3 "$CONVERGE_SKILL_DIR/scripts/tdd_impact_guard.py" validate --input -`；失败或无法证明的验收范围保持 `uncovered`，不得声称关联功能未受影响。

变更记录：修改 Converge Suite 自身的行为、入口、契约或兼容性时，必须更新本仓 `CHANGELOG.md` 的 `Unreleased`。执行目标项目的写入任务时，必须更新对应的 changelog；不存在时在目标项目根目录创建 `CHANGELOG.md`。优先沿用项目已有位置和格式，记录所有当前任务变更，并标注破坏性变化；不得根据最近 Git 提交混入其他任务的变更。

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_engine.py" select --mode <auto|pdlc|native> --kind <feature|fix|refactor>
```

Provider Schema v2；pdlc-v1/native-v1，`engine` 只由 binding 派生，不能成为第二真相；见 [TDD](references/tdd-providers.md)、[控制](references/execution-control.md)。

## 路由

`planned_task=true` 仅执行 capsule；否则按 [任务路由](references/task-routing.md) 用 `task_profile.py [--full-closure]` 分类；持久状态用 `freeze_routing` 冻结画像与请求摘要。全量收口只能由控制器作出明确决定，不能由关键词猜测；`full_closure_required=true` 禁止 `inline`，且必须先经 `converge-plan`。自治续跑使用 `converge-autonomy`，多模型 runner 使用 `converge-multimodel`；两者虽默认可发现，仍只在用户明确要求时触发并冻结对应扩展，自治 Hook 还须显式启用。仅当路由不是 `inline`、需 worker/恢复或请求并发/无响应时，读 [计划执行与无响应保护](references/execution-control.md)。

按已选路径渐进读取引用：一次只读一个必要 reference，不得在单个命令中拼接多个完整协议。`inline` 或普通同会话计划不读 worker、恢复、自治或全量收口资料；只有实际进入对应路径时才读取其 contract。

没有 worker lifecycle bridge 时，优先按 [Capsule Dispatch v1](references/capsule-dispatch.md) 用 `capsule_dispatch.py` 把冻结 capsule 投递到宿主实际创建的独立 task；仅 `delivered` 和稳定 task id 确认投递，不能当作 worker lifecycle、完成或清场证据。`indeterminate` 必须停止并交接，绝不重派。Codex CLI 与 Claude Code 的两个 concrete successor adapters 已可用；没有真实创建-task API 才输出同一 capsule 供用户启动。ChatGPT Desktop 当前仅有原生 subagent 工具、没有强制 leaf 能力，因此按 [Desktop Native Subagent v1](references/chatgpt-desktop-subagent.md) 视为 `unavailable`，不得创建 child。不得把 `spawn_agent`、wait timeout、消息投递或模型自述当作可恢复的 lifecycle 证据，`workers[]` 自动 lifecycle 仍保持关闭。

复杂、未知或长任务用 `converge-plan`，按独立可验收的业务切片执行；仅 `cross_session` 进 `converge-batch` 并先获 commit 授权。全量收口必须先用 `converge-plan` 建矩阵，终态须当前源码的 closure gate；缺项标 `uncovered`，不得宣称全部完成；见 [Plan Contract](skills/converge-plan/references/plan-contract.md)。

## 终态

写入需 writer lease，原身份释放：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/delivery_lease.py" release --root <root> --repo <common-dir> --workspace <worktree> --task-key <task> --run-id <run> --writer-id <writer>
```

仅 `{"status":"released"}` 成功。按 [审查编排](references/review-orchestration.md) 复核；无进展停止，禁止删测试、降阈值或扩大范围造绿。

Plan v6 审计见 [Plan Contract](skills/converge-plan/references/plan-contract.md) 与 [状态](references/state-schema.md)。`delivery_report.py` 按 [交付回执](references/reporting.md) 输出交付轮数 / 修复问题数 / 待处理项；外发另行授权。Suite 改动用 `converge-eval`。
