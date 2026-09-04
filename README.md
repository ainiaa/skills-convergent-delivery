# Converge Suite

一套面向 Codex 与 Claude Code 的软件交付 Skill：先把复杂工作拆成有限短任务，再让单任务有限收敛、独立审查保持只读、长计划稳定接力。

当前发布版本：[0.1.0](VERSION)。尚未创建 Git tag 的改动记录在 [Unreleased](CHANGELOG.md) 中。

## 3 步快速开始

1. 安装整个 Suite：

   ```bash
   curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
     | bash -s -- --latest --target all
   ```

2. 重启或刷新 Codex / Claude Code 的 Skill 发现；看不到 Skill 时运行 `bash install.sh --doctor --target codex --offline` 排查。

3. 复制下面的提示词开始一个任务（不确定时，先用 `converge`）：

   ```text
   使用 $converge 修复登录后跳转错误，运行相关测试并交付结果；不要发布或 push。
   ```

### 选哪个 Skill

| 你想做什么 | 用哪个 | 最短提示 |
|---|---|---|
| 实现一个功能、修 Bug 或重构，并完成验证 | `converge` | `使用 $converge … 并验证。` |
| 先拆复杂需求，只要计划、不改代码 | `converge-plan` | `使用 $converge-plan 拆成可验证任务，不修改代码。` |
| 只检查当前改动，不修改代码 | `converge-review` | `使用 $converge-review 检查当前 diff，不修改代码。` |
| 按已有的跨会话 Plan Contract 分批执行 | `converge-batch` | `使用 $converge-batch 执行 <plan>。` |
| 修改或验收 Converge Suite 自身规则 | `converge-eval` | `使用 $converge-eval 验收这次规则变更。` |
| 明确要求自治续跑或后台服务 | `converge-autonomy` | `使用 $converge-autonomy …` |
| 明确要求多模型协作 | `converge-multimodel` | `使用 $converge-multimodel …` |

最终回执会说明：结果、关键改动、实际验证范围和待处理项；发布、push、merge 等外发操作仍需你单独授权。更多安装与故障排查见 [使用与维护指南](docs/usage-guide.md)，两个运行时的完整调用示例见下文“调用当前 Skill”。

## 多模型协作

默认不启用；只有明确说“使用多模型配合开发”时才启用。它使用固定角色、动态流程：`Terra medium` 负责路由与取证，`Terra high` 负责规格与审查，`Luna high` 在受限范围内实现，`Sol high` 只裁决高风险冲突；验证始终由工具完成。

```text
使用 $converge-multimodel 配合开发修复支付重试问题：先按角色动态选择下一步，实施用 Luna high，遇到语义冲突再交 Sol high；运行相关测试，不要发布。
```

可以在同一句话指定角色，或说“使用 `<profile>` 配置”。角色不等于常驻 Agent：只有上下文隔离或独立审查确有收益时才创建 Agent；同一工作区只有一个写入者。Codex 与 Claude 均从同一冻结 profile 派发，并以“持久化 launch → 执行 → 持久化 result”闭环；只读 scout/reviewer 的输出必须是受限 JSON 结论，原文不会落入状态。明确独立的只读任务可由 controller 受控 fan-out（最多三个）后确定性汇总；它不允许并行写入、成员互聊或自动重试。二者只读限制的实现不同，Claude CLI permission 不是 OS sandbox。inline/tool 与非多模型路径不会创建 runner 生命周期。多模型结论不能替代真实测试、源码证据或发布授权；宿主无法真实指定或查询 worker 时会交接，不伪造派发。配置模板、优先级和外部只读审计见 [多模型协作](references/multi-model.md)。

## 为什么会有它

普通的“实现 → 检查 → 修复 → 再检查”很容易变成长对话：实现者既写代码又替自己解释，重复扫描消耗 token，用户还要不断追问“还有问题吗”。直接让一个 Agent 长时间执行大计划，又容易让上下文膨胀、范围漂移和验证变松。

Converge Suite 将五个职责拆开：planner 只拆任务，执行者只交付一个任务，reviewer 只找问题，scheduler 只接力，evaluator 只验收行为。每个角色都有明确输入、终态和重试上限；PDLC 可用时整体委托它的完整开发流程，不可用时仍能独立完成 TDD 与验证。

## 五个核心 Skill 与可选扩展

| Skill | 负责 | 不负责 |
|---|---|---|
| `converge` | 一个功能、Bug 或重构的范围、引擎选择、有限修复、验收和报告 | 只读评审、长计划调度 |
| `converge-plan` | 将复杂需求拆成有限、可验证任务，校验依赖并选择当前/全新/顺序执行 | 改业务代码、review、控制 PDLC 内部阶段 |
| `converge-review` | 基于证据的只读检查；支持意图审查和新上下文盲审 | 修改代码、决定发布 |
| `converge-batch` | 预检已有计划，按依赖派发独立任务，校验交接回执和最终验收 | 读业务代码、设计方案、实现或 review |
| `converge-eval` | 对冻结 control/candidate 做差分、多样本和历史逃逸行为验收 | 实现、代码评审或发布 |

核心能力：

- 默认按 `workflow Provider → Superpowers TDD → Matt Pocock TDD → native-v1` 稳定解析；通用 TDD 仅允许用 `--provider generic-tdd-v1 --tdd-skill <exact-SKILL.md>` 唯一选择。完整 Binding 冻结 manifest、task contract、真实入口、closure 与来源摘要。
- 复杂任务先形成 Plan Contract v6；每个 task 只有一个结果、明确范围、依赖、Source Receipt v2 基线、验证和完整收口矩阵。
- PDLC 每个 task 只形成一个有限 Provider Run，完整委托需求、设计、TDD、实现和阶段评审；根 Converge 只控制范围与证据，不复制内部阶段。
- PDLC 不存在时，原生流程仍提供根因定位、测试先行、语义审查和风险触发的稳定化检查。
- `checkpoint=same_session` 的多任务在同一会话顺序执行且不要求 commit；只有 `checkpoint=cross_session` 才进入 Batch 并请求一次本地 commit 授权。
- Codex、Claude Code 与单上下文先通过 Runtime Adapter 声明真实 dispatch/query/tree-query 或强制叶子能力；仅绑定真实 host query 原始观察的清场回执可标记 `host_observed`，普通参数永远是 `controller_attested`。父控制器直接调用当前宿主工具，worker 生命周期与无响应处理统一遵循 [执行控制](references/execution-control.md)。
- 结束时对账计划、diff 和新鲜证据，识别未完成项、计划变化与范围漂移。
- reviewer 的结果通过冻结请求绑定 task、验收、范围、baseline、源码和 reviewer，再由可执行 `review_contract.py normalize` 转成内部 Review v3 记录；代码变化后旧结论自动失效。
- `converge-eval` 只接受 Sample Receipt v4：control/candidate 必须解析为 Git commit/tree；judge、catalog、evaluator 与 Single State validator 来自修改前冻结的 Controller Snapshot；worker 绑定默认 managed state root 中的正式 Single State v10、evaluator role 与 host-observed 终态 tree receipt，不建立第二套 registry；touched paths 必须是 allowed scope 内不含反斜杠或 `..` 的仓库相对路径。evidence artifact 必须是候选仓库外的绝对 JSON 文件，并明确为 `evaluator_attested`，不能伪称宿主直接签名。缺少的验收和历史场景自动进入 `uncovered`，拒绝 `samples=["pass"]` 式自我声明。冻结运行时先校验受指纹保护的 bootstrap，再由快照自身执行协议校验；v16 的 legacy `extended` 快照保持其严格兼容语义。
- `scripts/trigger_eval.py` 会先完整校验数据集，再把每条 prompt 交给外部 selector 命令，报告精确匹配、错误数、混淆矩阵、precision/recall/F1，并绑定 dataset、selector 与 runner 指纹；artifact 必须对应 selector 命令文件。它只产生本地观察，`--release` 会固定以 `uncovered` 阻断，直到真实宿主 bridge 能签发 receipt。`test_trigger_evals.py` 只负责离线验证 runner 与数据契约。
- Batch 调度具备计划预检、强制 `planned_task/plan_id/task_id` 的最小胶囊、计划级 scheduler lease、幂等派发、结构化 receipt、暂停/恢复/停止和计划级验收。
- 执行拓扑由任务画像确定为 inline、planned、delegated 或 batch；风险只控制复核强度。普通任务最多一个 fresh reviewer，只有多任务或跨服务计划增加 integration review。
- 父控制器从 Git 展示整个工作区累计文件数与增删行；Codex 单步角标只表示当前动作，不表示任务累计规模。
- Codex 原生计划与 Converge 使用同一组稳定任务：简单任务直接更新宿主计划，持久任务通过确定性 Plan Projection/确认指纹同步，确认动作不会触发自循环。
- `converge-eval` 将最终覆盖分为 `known_acceptance`、`history`、`exploration` 和 `uncovered`，指定场景通过不等于未知范围为零。
- 单任务 Schema v10 分离包版本、Controller Snapshot 与 Provider Binding，并持久化路由、Review v3 源码轮次、计划同步确认、worker 最新进度和同 revision 清场回执。Batch state Schema v4 / Receipt v4 使用唯一 plan 状态、正式 delegate state、Source Receipt v2 与 Git 前序链。
- 复杂任务可冻结每个 leaf 的 model、reasoning effort、权限和预算。默认 `codex` profile 使用 Sol/Terra/Luna；`claude-code` profile 使用 Fable/Sonnet/Opus。两者都经相同的受限 CLI runner 启动：显式传 model/effort、只读角色无 shell、写入限独立 worktree，并生成同形 runner receipt；受限的最终响应只即时交给 controller，账本不保存原文。当前 OpenAI-compatible runner 仅开放已验证的 Zhipu research/review leaf。runner receipt 不冒充宿主 `host_observed`。
- 默认报告只输出面向用户的 summary；异常或显式 `--detail` 才附 Provider、阶段、worker 与检查诊断。

## Install

一次安装整个 Suite，默认同时安装到 Codex 与 Claude Code：

```bash
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/main/install.sh \
  | bash -s -- --target all
```

只安装一个运行时：

```bash
bash install.sh --target codex
bash install.sh --target claude
```

本地 clone 中执行 `bash install.sh --target all`。远程升级使用：

```bash
bash install.sh --upgrade --target all
```

远程来源可明确选择，三者互斥，且不能与本地 `--source` 混用：

```bash
# 跟随 main（默认行为）
bash install.sh --upgrade --latest --target all
# 已发布的稳定版本：解析为 Git tag v<version>
bash install.sh --upgrade --release <version> --target all
# 预发布或其他精确 Git tag
bash install.sh --upgrade --tag <tag> --target all
```

发布 tag 后，首次安装也应从同一个不可变 tag 获取 bootstrap 脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/ainiaa/skills-convergent-delivery/v<version>/install.sh \
  | bash -s -- --release <version> --target all
```

默认注册全部七个 Skill，方便显式调用和宿主发现；注册本身不会安装 Hook、启动 service 或运行模型。多模型只在用户明确要求时执行；自治 Stop Hook 仍须单独启用：

```bash
bash install.sh --target codex --autonomy
# 两个扩展入口均可单独撤销，其他 Skill 会保留：
bash install.sh --target codex --autonomy-uninstall
bash install.sh --target codex --multimodel-uninstall
```

安装器会先预检全部七个入口，再对每个软链接做原子替换；任一已知入口冲突时不会开始安装。普通文件或目录永远不会被 `--force` 删除。

### Uninstall

```bash
bash install.sh --uninstall --target all
```

卸载只移除七个运行时软链接，保留受管理源码；已启用的自治 Hook 或 service 可用对应的 autonomy uninstall 命令单独移除。

### Check your version

```bash
bash install.sh --version
bash install.sh --version --offline
```

运行只读安装诊断：

```bash
bash install.sh --doctor --target codex --offline
```

## 调用当前 Skill

### 显式调用

Codex：

```text
使用 $converge 实现这个功能并验证。
使用 $converge-plan 先拆成可验证短任务，不修改代码。
使用 $converge-review 检查当前 diff，不修改代码。
使用 $converge-batch 按已有计划逐批执行，每批调用 $converge。
使用 $converge-eval 验收这次 Converge 规则变更，不修改代码。
```

Claude Code：

```text
/converge 修复这个 Bug 并验证
/converge-plan 为这个复杂需求制定执行计划
/converge-review 检查当前改动
/converge-batch 执行 docs/plan.md
/converge-eval 验收 Converge 规则变更
```

完整安装后 Claude Code 可直接使用上述 `/` 命令；若当前会话未刷新发现结果，自然语言点名 Skill 仍可立即使用。

### 关键词触发

`converge` 的典型触发语：

- “按闭环开发实现这个功能”
- “闭环实现 / 处理 / 完成当前需求”
- “不要反复确认，修复并验证后再结束”
- “持续检查并修复，给出最终报告”

`converge-review`： “检查当前改动”“独立审查”“用新视角找问题”。

`converge-plan`： “先拆步骤再实现”“给出可执行计划”“按依赖决定执行顺序”。

`converge-batch`： “按 Batch 计划执行”“逐批接力”“调度多个独立任务完成计划”。

`converge-eval`： “差分验收 Converge 行为”“运行历史逃逸回归”“评估规则稳定性”。

只要方案时明确说“只给方案”；只检查时明确说“不修改代码”。Skill frontmatter 只是发现线索，无法保证任意自然语言都自动触发；显式点名最可靠。如需团队默认启用，可手工复制 [激活与触发](references/activation.md) 中的 `AGENTS.md` 片段；安装器不会自动改配置。

## 自治闭环（显式）

用户明确要求“闭环执行”时，Converge 先用 `autonomy_begin.py` 创建并 arm 当前 workspace 的唯一 Schema v11 active run，再在 Single State 冻结范围、验收、源码指纹和一次有限复审。控制器持续执行 gate 给出的一个下一动作；active run 未到证据充分的 `complete`、可恢复的 `blocked` 或需要授权的决策时不得输出 final，不会把“继续修复/还有问题吗”交还给用户。

Stop Hook 默认不安装。仅在本机已确认需要、并接受其宿主边界时显式启用：

```bash
bash install.sh --target <codex|claude> --autonomy
# 需要撤销时：
bash install.sh --autonomy-uninstall --target <codex|claude>
```

Codex 用 `queue --thread` 将 gate 的单一下一动作投递回同一 task；同一阶段和 action 只会成功投递一次，`report_history` 等非目标 revision 不会触发新的 queue，重复 Stop 会明确报 `no state progress`。initial audit finding 会确定性进入一次 `autonomy-repair`，因此是新的可投递动作而非 metadata 重试。Claude Code 2.1.246+ 用原生 Stop Hook `block` 在同一会话内继续，不会另起 `--resume` 进程。v11 native 无 finding 路径最多五次连续续跑；一次 finding 修复最多七次，仍低于 Claude 的八次宿主上限。预检不替代用户在目标宿主中的 live smoke，也不承诺后台或跨会话自行恢复。完整语义见 [自治适配](references/runtime-adapters.md) 与 [设计说明](docs/02_design/architecture/F20260827-autonomous-delivery-gate.md)。

需要跨会话服务恢复时，再显式安装 `bash install.sh --target codex --autonomy-service`，并用 `autonomy_begin.py --runtime service --service-runner <id> --verification-argv '<JSON argv>' --audit-argv '<JSON argv>' [--audit-findings-exit-code <1..255>]` 创建 run。未声明 finding 退出码时 audit 非零一律阻塞；声明后仅该退出码进入一次修复和 re-audit。service 仅支持低风险路由和默认 managed state/lease roots；语义风险用可重复的 `--risk-flag <risk>` 声明，高风险改走正常自治路径的独立 review。服务只在已落盘动作完成、冻结 verifier 与独立 audit 都通过后推进；重启时未知中的动作会阻塞，不会自动重跑。

## 工作方式

### 单任务执行

```text
冻结范围 → 建立验收 → 解析 Provider Binding → 有限计划 → 实现
→ 必要审查 → 有限修复 → 新鲜验证 → 交付回执
```

同一问题在同一阶段最多自动修一次；问题复现或没有客观进展时阻塞，不无限循环。高风险改动使用全新上下文的 `converge-review` 盲审；极高风险或用户明确要求时再增加意图审查。

复杂任务由 `converge-plan` 生成 Plan Contract v6，按独立可验收的业务切片形成多个 task，并冻结 Source Receipt v2 基线。每个 task 冻结自己的 Provider Binding；PDLC 仍完整负责一个 task 内部流程。已派发任务先校验 `planned_task=true`、`plan_id`、`task_id` 和 binding，再跳过画像与重新规划。

Plan v6 的 `checkpoint=same_session` 在同一工作区顺序执行，不要求 commit；每个 task 用 `source_before/source_after` 归属自身增量。只有显式 `checkpoint=cross_session` 才进入 Batch，并在 checkpoint 前请求本地 commit 授权。任务数量本身不产生 commit 权限。

worker 登记、宿主终态、清场和 watchdog 规则只在 [执行控制](references/execution-control.md) 维护。

### 长计划调度

```text
全量预检 → 冻结计划/wave → 独立任务（$converge）→ 校验 receipt
→ 下一 wave → … → 计划/diff/证据最终对账
```

调度器不读业务代码、不 review、不替任务决定技术方案。每批使用最小 context capsule；Batch Protocol v1 只承接跨会话 checkpoint 并逐项执行。派发结果不确定时查询原任务，不重复创建任务。

Codex Desktop 与 Claude Code 的 `workers[]` 自动 lifecycle 仍要求 bridge 提供同会话 `host_observed` tree query。没有 bridge 时，单任务、Batch 与跨会话均走手工 capsule 交接；普通 subagent 不承诺跨会话恢复。详见 [执行控制](references/execution-control.md)。

Suite 的所有委托和独立 evaluator 同样遵循上述唯一执行控制规则。普通 worker 永远是叶子；Batch 只派发新的 `controller-delegate` run，新 run 完成自己的子树清场后才能回传 receipt。

### Provider 选择

| 条件 | Provider Binding | 边界 |
|---|---|---|
| manifest 已适配的 PDLC | `pdlc-v1` | 按 task kind 路由真实入口；Converge 保留控制和最终验收 |
| 已适配 Superpowers / Matt Pocock TDD | 对应适配器 | 只委托一次红绿阶段 |
| 显式指定唯一 `--tdd-skill <exact-SKILL.md>` 且通过预检 | `generic-tdd-v1` | 不参加 auto、不扫描猜选；只采用测试方法，不接管循环和发布 |
| 都不可用 | `native-v1` | 使用内置有限 TDD 协议 |

Converge 始终是 controller。注册的新 workflow 或 TDD stage Provider 只要声明当前 task kind、完整入口闭包和兼容授权，即参与同一套发现与冻结。显式 `--provider <id>` 或已冻结 Provider 不可用时阻塞；auto 首次解析可以在业务写入前说明原因并降级。任务开始后冻结 manifest、task contract、实际入口、closure 和来源摘要，恢复时不允许热切换。

### 子代理进度

使用子代理时，worker 只发送客观 milestone；持有 writer lease 的父控制器根据精确宿主 query 使用 `delivery_progress.py observe` 生成 heartbeat。状态视图按内容去重，约 60 秒内保持可见，但不显示虚假百分比或 ETA。正式完成仍以宿主终态、源码和新鲜验证为准。

## 状态、多窗口与恢复

- 单任务状态：`~/.convergent-delivery/state/`，Schema v10（无 worker 的旧状态可保守迁移；旧 worker 状态必须人工恢复）。
- 冷恢复：`python3 scripts/delivery_state.py list --workspace <absolute-worktree>` 列出候选；`doctor` 在不写状态的前提下给出每个 run 的健康和下一动作。
- Batch 状态：`~/.convergent-delivery/batch-state/`，Batch Protocol v1 / state Schema v4 / Receipt v4；状态按 repo+plan 唯一定位，takeover 不复制状态。
- Batch scheduler lease：位于 Batch state 根下，按 `repo_id + plan_id` 唯一，默认两小时；过期后仅显式 takeover。
- writer lease：`~/.convergent-delivery/leases/`，默认两小时。

状态正式路径由 helper 推导；候选 JSON 只通过 stdin 传递，在目标目录内以 `0600` 临时文件、`fsync` 和原子替换写入，不把 `/tmp` 当真源。repo、任务/计划、run 与单调 revision 共同防止不同项目或窗口覆盖同一状态。

单任务恢复示例：

```bash
python3 scripts/delivery_next.py --state <state-file> --run-id <run-id> \
  --writer-id <writer-id> --revision <revision>
```

持久任务启动时先创建内容寻址的 Controller Snapshot，并把返回 descriptor 写入 controller identity；目标 workspace 随后修改 Converge 源码也不会改变本次运行的控制程序：

```bash
python3 scripts/controller_snapshot.py create --source "$CONVERGE_SKILL_DIR" \
  --root "$HOME/.convergent-delivery/controller-snapshots"
```

需要多模型或自治时才增加对应扩展：

```bash
python3 scripts/controller_snapshot.py create --source "$CONVERGE_SKILL_DIR" \
  --root "$HOME/.convergent-delivery/controller-snapshots" --extension multimodel
# Hook 自治只需 `--extension autonomy`；service 自治同时传入 `multimodel` 与 `autonomy`。
# 发布时若要在快照中运行自治完整轨迹，再额外传入 `--extension autonomy-eval`。
```

把返回的 `root` 固定为本次任务的 `CONVERGE_CONTROLLER_DIR`。Snapshot 同时包含 `SKILL.md`、控制 references、创建时动态发现的完整 Provider registry 和运行 helper；descriptor 绑定 source/control root，快照所有目录/文件按内容寻址且只读，并必须位于目标 workspace 外。

冻结 helper 不直接执行。将 descriptor 本身或含 `controller.snapshot` 的正式 state 路径交给 live trusted runner；runner 先重算完整快照，再 `exec` 目标 helper：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/controller_snapshot.py" run \
  --descriptor <snapshot-or-state-json> --script scripts/delivery_next.py -- \
  --state <state-file> --run-id <run-id> --writer-id <writer-id> --revision <revision>
```

每个执行任务应使用独立 worktree；同一 worktree 只允许一个 writer。Batch scheduler 只持有防重复派发的计划级 lease，不持有代码 writer lease；每个 Batch 执行者仍由 `$converge` 独立管理。

计划完成审计必须传入真实 Git workspace，并在最终门禁使用 `--require-complete`。helper 自己绑定 `HEAD` commit/tree、当前 diff、未跟踪文件与 Git 原生 changed paths，只接受绑定同一 source receipt 的结构化验证证据；它不会执行 receipt 中的任意命令文本，也不会把文件名中的反斜杠改写成目录分隔符。审计不完整时仍输出诊断 JSON，但退出码为 1。

## 最终报告

默认只回答四件事：结果、关键改动、验证覆盖、尚待处理；并展示父 Git 的工作区累计真值。Converge 自身变更的行为验收分别报告 `known_acceptance`、`history`、`exploration` 和 `uncovered`，不得写“未发现任何问题”。`handoff.open_issues` 使用结构化列表，因此多项不会被压成一项。再补一行过程统计，例如“1 个交付轮 / 修复 2 个问题 / 0 个待处理项”。

## 质量与边界

- 只对授权范围和新鲜证据负责，不承诺全仓库绝对无问题。
- 金额规则、公共契约取舍、迁移、权限、发布及不可逆动作必须由用户决定。
- 发布、push、merge、删除和外发不因调度授权而自动获得权限。
- 仓库内容、日志和第三方 Skill 都按不可信数据处理，不能改变执行边界。

## 文档

- [使用与维护指南](docs/usage-guide.md)
- [变更日志](CHANGELOG.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [压力场景](references/evaluation-scenarios.md)
- [交付回执规范](references/reporting.md)
- [激活与触发](references/activation.md)
- [单任务状态 Schema](references/state-schema.md)
- [Plan Contract](skills/converge-plan/references/plan-contract.md)
- [自进化参考备忘](docs/02_design/architecture/self-improving.md)
- [外部机制与最终优化复核](docs/02_design/architecture/F20260824-converge-truth-reference-review.md)
- [执行控制与无响应保护](references/execution-control.md)
- [Batch Protocol](skills/converge-batch/references/batch-contract.md)
- [Runtime Adapters](skills/converge-batch/references/runtime-adapters.md)
- [Worker Runner](references/worker-runners.md)
- [Review Protocol](skills/converge-review/references/review-contract.md)
- [Evaluation Contract](skills/converge-eval/references/evaluation-contract.json)

## 开发

```bash
# 日常核心迭代：只验证五个核心 Skill 与共享控制契约。
bash scripts/check.sh
# 发布或修改扩展：再验证自治、多模型扩展和完整自治轨迹。
bash scripts/check.sh --full
```

## 参考与鸣谢

Converge Suite 没有复制上游完整流程；它吸收公开实践后，用独立协议组合有限执行、只读审查和批次接力。感谢：

- [kanfu-panda/pdlc-skills](https://github.com/kanfu-panda/pdlc-skills)：完整 PDLC 阶段、质量闸门、状态推进和循环控制。
- [obra/superpowers](https://github.com/obra/superpowers)：系统化调试、TDD、完成前验证、fresh-context review 和 Skill 压力测试。
- [obra/external-subagents](https://github.com/obra/external-subagents)：Codex CLI 外部 leaf 的可恢复 launch/receipt 边界；本 Suite 仅采用其“外部 runner 不伪装宿主 worker”的原则，不复制其 state engine。
- [GitHub Spec Kit](https://github.com/github/spec-kit)：Spec → Plan → Tasks → Implement 的追溯结构。
- [gstack](https://github.com/garrytan/gstack)：计划就绪检查、决策记录和 plan-vs-diff 完成审计。
- [mattpocock/skills](https://github.com/mattpocock/skills)：公共行为 seam、垂直切片和避免测试实现细节。
- [grill-with-docs](https://www.skills.sh/mattpocock/skills/grill-with-docs)：逐一追问并结合代码库、领域词汇、`CONTEXT.md` 与 ADR 形成必要决策；本 Suite 只采用“未闭合决策先澄清”的边界，不默认生成文档或 issue。
- Builder.io 的 planning/review Skills 与公开的 delegate/taskflow 实践：启发了高风险计划仲裁、fresh worker、依赖 wave 和结构化交接。
- [skills.sh](https://skills.sh/) 上公开的 Skill 结构与触发实践。
- [石头关于“审查—修复—再审查”和独立 Batch 调度器的实践文章](https://mp.weixin.qq.com/s/Ea8g3uH5f7kPKR0B-39cTg)：启发了 reviewer/scheduler 职责拆分、最小上下文和分批交接。
- Codex `skill-creator`：渐进式加载、可执行校验和界面元数据规范。

## 许可与反馈

- [MIT License](LICENSE)
- [Security Policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [GitHub Issues](https://github.com/ainiaa/skills-convergent-delivery/issues)
