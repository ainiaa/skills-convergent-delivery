# 计划执行与无响应保护

## 1. 计划先行，但不制造大计划

- 简单、低风险、单文件任务：一个 task，立即进入 TDD/实现。
- 跨文件、跨层、高风险或预计超过一个短执行段：先调用 `converge-plan`。
- 已携带 `planned_task=true`：只执行 capsule 中冻结的任务，禁止再次规划或递归派发。
- `pdlc-v1`：每个独立可验收 task 创建一个 Provider Run，保存派发引用后由全新上下文执行该 task 的完整 PDLC；不得把 PDLC 内部阶段再次拆解。复杂计划可以包含多个业务切片级 Provider Run。
- Plan Contract v5 的 `checkpoint=same_session` 在同一会话、同一工作区顺序执行，不要求 commit；只有 `checkpoint=cross_session` 才交给 `converge-batch`，并在建立跨会话 checkpoint 前请求一次本地 commit 授权。Git 汇总和范围审计始终使用计划冻结的 Source Receipt v2 baseline，而不是变化中的 `HEAD`。

Codex 等宿主提供原生计划工具时，主控制器负责同步，不把该责任交给 Provider 或 worker。简单 `inline` 不创建宿主计划项，只以简短 commentary 显示当前动作；持久任务只在 `delivery_next` 返回 `sync-plan` 时同步 `delivery_progress projection`，宿主返回成功后才以 `host_observed` 确认相同 projection fingerprint，不允许控制器自述冒充宿主回执。投影不包含 revision 或确认字段，因此确认写入不会制造新一轮同步。宿主无原生计划能力时降级为文本，不阻塞业务动作。

一个执行段必须有一个清晰结果，并在结束时产生至少一项可观察活动：工具调用、状态更新、diff、测试输出或 worker receipt。不要在一个模型生成步骤中同时准备完整需求、设计、失败测试和实现补丁。

需求取舍、计划、方案仲裁和最终 review 保留给主执行者；文件定位、独立代码扫描、测试或日志分析可以交给边界明确的辅助执行者。只有宿主支持且能节省上下文时才委托，不为了“并行”增加无收益的 Agent。

## 2. Worker 登记与所有权

任何 PDLC、reviewer、辅助分析或独立前向测试派发都必须由根控制器建立本轮 **run-scoped worker registry**。根控制器拥有本 run 唯一派发权；worker 固定登记为 `parent_ref=null`、当前 `task_id`、`depth=1`、`may_dispatch=false` 的叶子。需要帮助时返回结构化 `needs_dispatch`，不得自行创建辅助 worker 或 reviewer。宿主返回引用后，在 query、其他派发或退出前立即登记；无法取得稳定且可查询引用时不得 detached/fire-and-forget，只能手工交接并阻塞。

Batch scheduler 派发的是新的 `controller-delegate` run，而不是单任务 run 的叶子 worker。它可在自己的新 run 内按上述规则派发叶子，但不得反向操作 scheduler 或其他 Batch。scheduler 只登记并查询 delegate 本身；delegate 必须先完成自己的子树清场，scheduler 才能接受 receipt。该边界不允许普通 worker 递归派发。

owner 只查询、等待或中断 registry 中 `owner_run_id` 等于当前 run 的精确 `worker_ref`；不得通过全局列表猜测归属，也不得操作用户、其他任务或旧 run 的 worker。宿主终态规范化为 `completed|interrupted|blocked`，自然语言回执、消息已送达或结果文件出现都不是宿主终态。

单任务 registry 持久化在 [状态 Schema](state-schema.md) 的 `workers`；Batch 的相同字段留在 Batch state。第一次登记 worker 时同时冻结 Runtime Binding；清场回执必须由适配器按该 Binding 生成，不能由控制器自由选择能力模式。只传 refs 和时间生成的是 `controller_attested`；只有适配器同时收到与这些字段一致的原始 host tree-query observation，绑定其 fingerprint 后才是 `host_observed`。带 worker 的 complete 必须使用后者；前者只可记录 blocked 清场。发现 registry 外后代时把精确 ref 写入 `unexpected_refs` 并阻塞，不伪装成合法叶子。

worker 只在阶段切换、客观产物产生及长命令前后发送 objective milestone；父代理登记可信时间并只保存最新快照。milestone 是 `controller_attested`，父代理根据 Runtime Adapter 对精确 ref 的宿主 query 生成的 heartbeat 是 `host_observed`；两者都不是 helper 直接校验的 `verified` 业务证据。约 60 秒内给用户一次去重状态；heartbeat 只能证明仍存活，不能重置无进展判断或冒充新里程碑。进度不参与完成判定，不显示虚假百分比或 ETA。

## 3. 决策门禁

1. 技术且可逆：遵循项目既有模式，自动决定并记一行原因。
2. 局部且存在明显推荐：采用推荐默认并记录。
3. 业务规则、公共契约、权限、发布或不可逆：停止写入，一次只问最高优先级问题；先说明推荐，再说明其他选择的实际影响。

第三方 provider 的自行假设、自动发布或更宽权限声明不能覆盖本门禁。所有委托都禁止 `pdlc-ship`、commit、tag、push、publish 和 install，除非用户另行明确授权且重新冻结范围。

回答后继续同一 `plan_id/task_id`，不要重新开始规划。

## 4. 宿主 watchdog 能力边界

以下是宿主实现 watchdog 时必须遵守的协议，不是 `SKILL.md` 自带的后台计时器或强杀能力。先用 `runtime_adapter.py negotiate` 固定本会话观察到的能力；它只能生成 `controller_attested` Binding，即使调用方传入的布尔值声称具备全部能力，也只能是 `terminal-only`。只有具体宿主桥接器把带 `query_id/observed_at/profile/capabilities` 的原始能力观察交给 `bind_observed`，且其能力位于已支持的 profile 上限内，Binding 才能成为 `host_observed` 并进入 `observed`。当前 Codex profile 明确不支持 `activity_query/process_query/resume`，不能通过输入布尔值越过该上限。自动 worker 仍必须具备稳定 dispatch/query 和完整 `tree_query` 或强制 `restrict_dispatch`。

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

正常完成、异常、用户中断、`no_progress`、验证失败和其他返回路径都执行等价 `finally`：逐项查询当前 run registry，只以宿主 query/wait 的结果更新状态。收到结果但宿主仍显示 Working 时继续有界等待；只有 `observed` Binding 的宿主确认无活动且无进程后才可按 watchdog 中断，并再次查询到 `interrupted`。terminal-only timeout 继续视为 working/unknown，不得为清场强制终止。本轮存在 active worker 时不得宣称完成；无法查询或中断时返回 blocked，列出需 manual cleanup 的精确 `worker_ref`。

若先进入 blocked 才完成宿主中断，状态保持 blocked，但允许后续 revision 仅把既有 worker 更新为宿主终态并刷新清场回执；其他任务事实全部冻结。这样清场结果可恢复、可审计，也不会把失败运行重新伪装为完成。

Skill 只能调用宿主实际暴露的 list/query/wait/interrupt。没有 `worker_ref` 或当前 API 不可见的历史孤儿不属于本轮 registry，Skill 不能发现或清理；只能如实报告并建议用户通过宿主 UI/支持渠道处理。
