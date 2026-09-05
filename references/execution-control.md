# 计划执行与无响应保护

## 1. 计划先行，但不制造大计划

- 范围局部、单步骤、验证局部且业务已消歧的任务：一个 task，立即进入 TDD/实现。
- 通用 fast path 已停用；文档和纯格式改动也走完整路由，直到 formatter 专属 contract 可证明无语义变化。
- 跨模块、跨层、依赖步骤、未知验证或预计超过一个短执行段：先调用 `converge-plan`。
- 风险只提高 review/verification；局部高风险任务保持 `inline`，不得以计划替代高风险验证或独立盲审。
- 已携带 `planned_task=true`：只执行 capsule 中冻结的任务，禁止再次规划或递归派发。
- `pdlc-v1`：每个独立可验收 task 创建一个 Provider Run。控制器解析冻结 entrypoint，并显式调用对应 `$pdlc-feature|fix|refactor` 完整执行；Provider Binding 或 `pdlc-run` 不算调用，禁止 native 混入。入口不可解析或激活即 `blocked_environment`；PDLC 证据返回 Converge 后再收口，不得拆解其内部阶段。复杂计划可含多个业务切片级 Provider Run。
- Plan Contract v6 的 `checkpoint=same_session` 在同一会话、同一工作区顺序执行，不要求 commit；只有 `checkpoint=cross_session` 才交给 `converge-batch`，并在建立跨会话 checkpoint 前请求一次本地 commit 授权。Git 汇总和范围审计始终使用计划冻结的 Source Receipt v2 baseline，而不是变化中的 `HEAD`。

Codex 等宿主提供原生计划工具时，主控制器负责同步，不把该责任交给 Provider 或 worker。简单 `inline` 不创建宿主计划项，只以简短 commentary 显示当前动作；持久任务只在 `delivery_next` 返回 `sync-plan` 时同步 `delivery_progress projection`，宿主返回成功后才以 `host_observed` 确认相同 projection fingerprint，不允许控制器自述冒充宿主回执。投影不包含 revision 或确认字段，因此确认写入不会制造新一轮同步。宿主无原生计划能力时降级为文本，不阻塞业务动作。

### 分步可见交付

用户明确要求逐步或分步执行时，控制器负责以下展示；一次只推进当前可执行步骤，不把多步结果留到最终回复才一起公布。

- 先展示既有计划的步骤清单和当前步骤；以计划中的可验收任务为单位，不把每次读文件、工具调用或 Provider 内部阶段拆成新任务。
- 开始一步前，在用户可见的 commentary 中说明步骤编号、目标和修改范围。
- 结束一步后，先展示实际改动、已执行验证及结果、遗留问题，再更新“已完成 / 进行中 / 待执行 / 阻塞”的进度视图，明确下一步。尚在运行、验证失败或未覆盖的检查不得写成已通过。
- 复用上文的宿主计划投影；没有计划工具时直接给文本清单。展示必须在折叠工具输出和内部推理之外，不新增可写台账，也不把冻结 Plan 的 `pending` 定义当作执行状态修改。
- 已授权且无阻塞时自动进入下一步；只有用户要求每步确认或遇到既有决策门禁才暂停。恢复时从实际状态和证据继续，不为补展示重做已完成的修改或验证。

例如：`第 1 步完成：已修复退出后的残留写入；回归检查通过；无遗留。进度：1 已完成，2 进行中，3 待执行。第 2 步：校验评测报告完整性，范围为比较器及其测试。` 验证失败时改报实际失败和阻塞原因，不进入依赖该结果的步骤。

依据：[HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) 的可检查步骤和规则单一来源；采用阶段结果展示，不引入额外控制循环或状态。行为验收：两步修复中，第 1 步结果必须先于第 2 步修改可见；无宿主计划工具时仍有文本进度；失败、需确认和恢复路径不得误推进或重做。简单未要求分步的任务保持原路径。

一个执行段必须有一个清晰结果，并在结束时产生至少一项可观察活动：工具调用、状态更新、diff、测试输出或 worker receipt。不要在一个模型生成步骤中同时准备完整需求、设计、失败测试和实现补丁。

## 1.1 模型陈述与事实门禁

目标是防止正常模型因误解、遗漏、偷懒或自信表述而把未完成的工作说成完成：不能只凭模型自述、自然语言回执、计划文本或“测试已通过”的说明推进状态、通过验收或对用户宣称交付。每项结论必须由已执行命令的输出、结构化 Evidence Receipt、实际 Git/状态机结果或宿主可观察终态支撑；证据缺失、未知或陈旧时如实标为未验证/blocked，不用补充叙述凑完成。

这不是针对恶意篡改本地文件、宿主或调用链的安全承诺。不为恶意篡改额外引入签名服务、后台守护、平行日志或第二状态；当前范围内优先让正常控制路径不能因模型自述而放行。若未来需要对抗恶意来源，先由宿主提供可验证 provenance，再单独设计和授权。

## 1.2 显式自治交付

用户明确要求闭环执行时，`autonomy_begin.py` 先创建对应运行模式的不可变 Controller Snapshot，再在内存中冻结并 arm Schema v11，取得 writer lease 后一次写入唯一 active run；创建失败必须释放刚取得的 lease，并确认唯一成功回执 `{"status":"released"}`，否则输出 lease cleanup 诊断，不能留下 v10/v11 之间的活跃状态窗口。没有该 active run，Hook 必须视为普通任务，不能假定安装 Skill 就会续跑。`autonomy_gate.py` 只读该状态并返回一个 Runtime Action；它不会执行模型文本、推进业务状态或以 DONE 字样放行。Codex Stop Hook 只在 active run 且取得 `session_id` 时用 `codex queue` 将这个唯一 action 投递回同一 task，并以 state path/stage/action 的私有回执保证元数据 revision 不会重新投递同一动作。投递失败、缺少 session 或重复 Stop 无进展时不重投，而是确定性写为 `blocked/no_progress` 并释放 lease。Claude Code 2.1.246+ Stop Hook 直接返回带同一 action 的 `decision:block`，由宿主继续当前会话，不能从 Hook 另起 `--resume` 进程。控制器执行后再以新状态重新裁决，不能把完整流程塞回下一段 prompt；native 无 finding 路径最多五次连续续跑，一次 finding 修复最多七次，均低于 Claude 的八次宿主上限。active run 未到 `complete|blocked` 时，控制器不得输出 final。安装必须显式使用 `bash install.sh --target <codex|claude> --autonomy`，可用 `--autonomy-uninstall` 精确撤销；未通过本机预检的宿主仍走普通模式。无进展、无效状态、多个 active run 或权限边界必须成为有证据的 `blocked`，不能无限重试。详见 [自治 Stop Hook 适配](runtime-adapters.md)。

需要独立服务时，`autonomy_begin.py --runtime service` 必须同时带冻结的 `--task-profile-json`、implementer runner、JSON `verification_argv` 与不同的 JSON `audit_argv`；service 仅接受 low-risk route、高风险必须保留独立 review，且当前只接受 LaunchAgent 已知的默认 state/lease roots，避免后台服务失联。语义风险由冻结画像和 `--risk-flag` 显式声明并与路径风险合并。service 先写动作 intent/running，再在外部 runner 启动前写入冻结 `runner_launches`，收到回执后写入匹配的 `runner_results`；模型回执只可形成 observed。独立 verifier 通过后，controller 以 verifier 的 source receipt 原子推进阶段并 committed；最终阶段还必须由独立 audit 在同一源码上通过，才归档旧验收、记录当前 pass audit 并 complete；失败 verifier 与 audit 都必须以 fail check 保存 receipt。模型只改冻结工作区，绝不写 managed state。任何可写状态的 service 异常必须尽力持久化为 `blocked`，且终态仅在 lease 返回 `released` 后才算清场；已识别但无效、非对象或不可解析的 managed state 必须输出诊断，但不得阻止同一 state root 中健康 run 继续执行；仅有这类诊断而无 active state 时成功退出，避免 LaunchAgent 无限重启。直接指定无效 state 必须返回手工恢复诊断，直接指定有效的 Hook state 必须拒绝且不得改写其 state 或释放 lease，且指定 state path 必须与 state root 的规范路径相同。恢复遇到 running 结果一律视为未知并 block，不会为“再试一次”重放外部模型调用。

service 只执行 `execute-inline` 或带 `phase` 的 `verify`。其他宿主 controller action 必须由同会话控制器处理；service 遇到它们立即停止，绝不降级为普通模型阶段，并写为 `blocked/no_progress`。

需求取舍、计划、方案仲裁和最终 review 保留给主执行者；文件定位、独立代码扫描、测试或日志分析可以交给边界明确的辅助执行者。只有宿主支持且能节省上下文时才委托，不为了“并行”增加无收益的 Agent。

## 2. Worker 登记与所有权

使用 bridge 自动 lifecycle 的 PDLC、辅助分析或独立前向测试 native worker，必须由根控制器建立本轮 **run-scoped worker registry**。没有 bridge 时一律手工交接，不能登记 registry。root controller 拥有本 run 唯一派发权；registry worker 固定登记为 `parent_ref=null`、当前 `task_id`、`depth=1`、`may_dispatch=false` 的叶子。需要帮助时返回结构化 `needs_dispatch`，不得自行创建辅助 worker。normal/high reviewer 必须走 external runner，不进入 native registry。宿主返回引用后，在 query、其他派发或退出前立即登记；无法取得稳定且可查询引用时不得 detached/fire-and-forget，只能手工交接并阻塞。

Batch scheduler 派发的是新的 `controller-delegate` run，而不是单任务 run 的叶子 worker。它可在自己的新 run 内按上述规则派发叶子，但不得反向操作 scheduler 或其他 Batch。scheduler 只登记并查询 delegate 本身；delegate 必须先完成自己的子树清场，scheduler 才能接受 receipt。该边界不允许普通 worker 递归派发。

owner 只查询、等待或中断 registry 中 `owner_run_id` 等于当前 run 的精确 `worker_ref`；不得通过全局列表猜测归属，也不得操作用户、其他任务或旧 run 的 worker。宿主终态规范化为 `completed|interrupted|blocked`，自然语言回执、消息已送达或结果文件出现都不是宿主终态。

单任务 registry 持久化在 [状态 Schema](state-schema.md) 的 `workers`；Batch 的相同字段留在 Batch state。只有 frozen route 为 `delegated`、同会话 `host_observed` Runtime Binding 含 `tree_query` 时才能登记 `workers[]` native worker；controller-attested Binding、`restrict_dispatch` 和跨会话任务都不能使用自动 lifecycle。清场回执必须由适配器按同一 Binding 和原始 host tree-query observation 生成；发现 registry 外后代时把精确 ref 写入 `unexpected_refs` 并使 state 立即转为 `blocked`，不伪装成合法叶子。

worker 只在阶段切换、客观产物产生及长命令前后发送 objective milestone；父代理登记可信时间并只保存最新快照。milestone 是 `controller_attested`，父代理根据 Runtime Adapter 对精确 ref 的宿主 query 生成的 heartbeat 是 `host_observed`；两者都不是 helper 直接校验的 `verified` 业务证据。约 60 秒内给用户一次去重状态；heartbeat 只能证明仍存活，不能重置无进展判断或冒充新里程碑。进度不参与完成判定，不显示虚假百分比或 ETA。

## 3. 决策门禁

1. 技术且可逆：遵循项目既有模式，自动决定并记一行原因。
2. 局部且存在明显推荐：采用推荐默认并记录。
3. 业务规则、公共契约、权限、发布或不可逆：停止写入，一次只问最高优先级问题；先说明推荐，再说明其他选择的实际影响。

第三方 provider 的自行假设、自动发布或更宽权限声明不能覆盖本门禁。所有委托都禁止 `pdlc-ship`、commit、tag、push、publish 和 install，除非用户另行明确授权且重新冻结范围。

回答后继续同一 `plan_id/task_id`，不要重新开始规划。

## 3.1 Capsule Dispatch

跨上下文但不需要父控制器跟踪旧 worker 时，按 [Capsule Dispatch v1](capsule-dispatch.md) 使用宿主实际创建的新 task 自动投递冻结 capsule。成功创建只得到 `delivered` 和宿主 task id；successor 是独立 controller，不属于父 run 的 `workers[]`，也不让父 run 因此 complete。调用结果为 `indeterminate` 时不得再次创建 task；保留 capsule 并 `blocked`。宿主未暴露创建 API 时才由用户启动该 capsule。

这条路径不替代 Batch 的 receipt 链，也不能恢复或终止任何旧 worker。当前 package 不提供 concrete host bridge，因此下面的 worker registry 只描述将来由宿主 bridge 单独实现的能力，不能由普通 Python helper 或 JSON 输入启用。

ChatGPT Desktop 当前会话的原生 child 另见 [Desktop Native Subagent v1](chatgpt-desktop-subagent.md)：它经宿主 `spawn_agent` 创建、只在当前会话内由控制器等待或停止，不是 Capsule Dispatch 的独立 successor，不能进入 worker registry。

## 4. 宿主 watchdog 能力边界

以下是 concrete host bridge 将来实现 watchdog 时必须遵守的协议，不是 `SKILL.md` 自带的后台计时器或强杀能力。`runtime_adapter.py negotiate` 只能生成 `controller_attested` Binding；公共 `bind_observed` 明确拒绝普通 JSON 输入，当前 package 没有可启用 lifecycle 的 bridge。不能因输入布尔值、profile 名称或消息投递而越过该边界。Capsule Dispatch 的 delivery ack 不参与本节。

`watchdog_action` 返回的不是自然语言建议，而是带精确 `task_id/worker_ref` 的 `query|wait|interrupt|block` Runtime Action；控制器只能执行该动作。没有 `wait` capability 时它返回 `query`，不会生成无法执行的 wait。只有 `host_observed` Binding 同时具备 `activity_query`、`process_query`、计时 `wait`、`interrupt` 和同一任务 `resume` 时才是 `observed`，执行者才能自动完成软探测、硬中断与恢复。其他 automatic Binding 一律是 `terminal-only`：可等待和查询终态，但 `wait` 超时只表示结果未知且仍可能在运行，不能累积为无进展、触发探测/中断或消耗恢复预算。manual 和 terminal-only 只能保持可见进度、保存 capsule/receipt 并阻塞或交给用户手工恢复，不能声称已经中断、恢复或清场。

活动信号包括 commentary、工具调用、状态 revision、diff、日志增长、子任务回执或仍在运行的测试/构建/PDLC 进程。

- **软探测（约 90 秒）**：仅 `observed` Binding 可用。所有宿主活动信号均为空且没有运行进程时，保存 worker 最近的 objective milestone、source/diff 与验证输出为 partial handoff，再向用户说明当前 task，并对原任务/进程执行 `query`。这个 partial handoff 只是可恢复进度，不是完成回执；排队消息或没有回复均不能当作进展。
- **硬中断（约 180 秒）**：仅 `observed` Binding 可用。软探测后仍由宿主确认无任何活动且没有运行进程，才执行返回的精确 `interrupt` action；保留 `plan_id`、`task_id`、`worker_ref` 和上述 partial handoff。
- 中断后只恢复同一 `worker_ref` 或同一 task，**最多自动恢复一次**。仅 `observed` Binding 可自动恢复；Batch 必须先把 `worker_ref` 和 `recovery_count=1` 持久化；仍无进展则以 `no_progress` 阻塞，不重新派发、不扩大任务。
- 测试、构建、PDLC 或子任务仍在运行时不触发硬中断；按不超过 60 秒的可见节奏汇报等待状态。
- 用户明确 stop 可以按宿主中断；排队消息、自然语言回执和重复 `wait` timeout 都不是活动或停滞证据。

连接中断或派发结果不确定时，必须先查询同一 `worker_ref`。没有可靠引用时阻塞或输出手工交接 capsule，不能创建第二个执行者。

## 5. 三类有限循环

三类循环互不嵌套，控制器只核对边界与客观证据，不复制 Provider 内部的 PDLC/TDD 阶段。

### 实现循环

Provider 负责在当前 task 内完成有效红灯、最小实现和绿灯。红灯转绿且最后生产变更后的目标验证新鲜通过时停止；同一问题指纹最多自动修复一次，修复后复现或没有客观改善时立即停止并阻塞。Converge 不在 Provider 外再跑一套 requirements/design/TDD/implementation/review。

### 风险复核循环

低风险由主执行者自检；普通任务由一个 fresh reviewer 接收两个有序单轴请求，先 spec、后 quality；高风险使用一个 blind reviewer并保持相同顺序。finding 按根因合并，最多一次修复和一次定向复核；repair fingerprint 必须与 repair budget 的 1→0 同步，`re_review|closure` 请求必须与 re-review budget 的 1→0 同步。重复 finding 或无客观进展即停止并阻塞，不重新开放式扫描。路由、评估次数、Review v3 源码轮次、绑定请求和剩余预算写入 Single State v10，不能只留在提示词中。

### 全局集成审查循环

`integration_required` 由 frozen task profile 的多任务/跨服务事实确定性生成；必需时初始 budget 为 1，没有请求不得提前写 0，执行一次 integration 审查时必须同步消费为 0。integration 只覆盖跨任务接口、组合行为和计划级验收；单任务不创建 integration reviewer。integration finding 最多一次修复和一次 closure 复核，随后无论通过或阻塞都停止。交付前还必须确认本轮 active worker 数为 0。

## 6. 执行结束与清场屏障

对 Plan Contract 运行 completion audit，再对最后生产 diff 运行新鲜验证。审计为 `PARTIAL`、`NOT_DONE`、`CHANGED` 或存在 `scope_drift` 时，不得用“已完成”掩盖差异。

### 6.1 全量收口矩阵

“修复全部已知问题”“还有没有其他问题”“深度审查”“彻底检查”“不留遗漏”以及“全部完成”都要求控制器明确决定是否为全量收口；该决定必须作为 `full_closure_required=true` 冻结，不能交给关键词匹配。开始修改前必须调用 `converge-plan`，以 CodeGraph/实际调用链冻结有限矩阵；已带 `planned_task=true` 的 capsule 也必须携带该矩阵，缺失即 `blocked`，不能借递归保护跳过。

每一条受影响的数据或控制链都必须覆盖：`输入`（提示词、文件、CLI/API 和解析边界）、`冻结`（范围、验收、配置、源码身份）、`副作用`（写入/外部调用及其所有共享入口和 caller）、`回执`（结果、状态完成门禁）以及`恢复`（异常、并发、超时、重试和终态清场）。将每一格映射为 task acceptance 或 `final_acceptance`；每项必须有最后修改后的新鲜正/负向证据，或有可核查的 `not_applicable` 理由。`plan_check.py audit --require-complete` 继续作为唯一完成门禁。

矩阵中未能审到、不能运行或证据不足的格必须显式写为 `uncovered`；它不阻止交付已验证的局部修复，但阻止“全部已修复”“没有其他问题”这类结论。它证明的是冻结范围内的收口，不声称能数学证明仓库不存在未知 bug；一次收口后没有新证据时，后续复查只报告“无新增问题”和现有 `uncovered`，不重新开始无界搜索。

正常完成、异常、用户中断、`no_progress`、验证失败和其他返回路径都执行等价 `finally`：逐项查询当前 run registry，只以宿主 query/wait 的结果更新状态。收到结果但宿主仍显示 Working 时继续有界等待；只有 `observed` Binding 的宿主确认无活动且无进程后才可按 watchdog 中断，并再次查询到 `interrupted`。terminal-only timeout 继续视为 working/unknown，不得为清场强制终止。本轮存在 active worker 时不得宣称完成；无法查询或中断时返回 blocked，列出需 manual cleanup 的精确 `worker_ref`。

若先进入 blocked 才完成宿主中断，状态保持 blocked，但允许后续 revision 仅把既有 worker 更新为宿主终态并刷新清场回执；其他任务事实全部冻结。这样清场结果可恢复、可审计，也不会把失败运行重新伪装为完成。

Skill 只能调用宿主实际暴露的 list/query/wait/interrupt。没有 `worker_ref` 或当前 API 不可见的历史孤儿不属于本轮 registry，Skill 不能发现或清理；只能如实报告并建议用户通过宿主 UI/支持渠道处理。
