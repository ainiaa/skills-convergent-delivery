# 变更日志

本项目的重要变更记录在此文件中，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

- 修复任务模式越界：根入口现在以最新用户请求为准；最新请求明确为只读审查、检查、对比或仅报告时，必须转入 `converge-review` 并禁止沿用历史写入授权。只读路径只能报告 finding、证据和建议修复，后续明确要求修复才可重新进入写入流程。
- TDD/Impact Trace 升级为 v5：trace criterion 必须精确覆盖当前验收项，状态拒绝重复验收项；coverage 也以最终源码 observed receipt 和阈值进入 completion gate，native rerun 还必须与项目解析出的 coverage argv/阈值一致；CodeGraph 必须执行由 impacts 派生的精确查询。新增无副作用 rerun，在 complete 前实际重跑最终绿灯、coverage、mutation 与图谱命令并拒绝生成工件污染源码；time、timezone、不可逆操作加入对应 integration 覆盖要求。Evidence Receipt 拒绝敏感 argv（含 Authorization/Bearer）并限制参数与 trace 总大小，trace CLI 在 JSON 解析前限制输入字节；最终复跑对每条冻结命令默认限时 600 秒、最多可调至 3600 秒。明确本地回执不提供同一工作区用户对抗篡改的密码学保证。修复 .NET coverage parser 误把任意 `threshold` 参数当作 gate 的问题，拒绝由任意命令伪造显式 coverage 阈值，并避免 native coverage 策略误拦截 PDLC。
- TDD/Impact Trace 升级为 v2：红绿测试必须引用 `evidence_contract.py` 真实执行生成的 observed Evidence Receipt，红灯绑定不同于最终版本的源码、绿灯绑定最终源码；补充公共 seam、单一可观察行为和外部边界 mock 规则。原生 `native-v1` TDD coverage 默认门槛为 >=85%，项目配置优先使用 `docs/00_standards/test-commands.yml` 的 coverage 命令和 `quality-targets.yml` 阈值，无法运行时保持 `uncovered`。
- TDD/Impact Trace 升级为 v3：每个测试以 selector 绑定红绿回执的实际 argv，红灯只接受 `missing_behavior` 或 `assertion`，拒绝编译、Mock 和环境失败；新增无副作用的原生 coverage 策略解析器，安全 argv 优先、配置阈值其次、默认 >=85%，无法解析或执行时保持 `uncovered`。
- TDD/Impact Trace 升级为 v4：已知 runner 校验 selector 语法，绿灯固定重跑一次检测不稳定，最终影响链绑定 CodeGraph 执行回执；高风险 integration/contract 测试要求 mutation 回执。原生 coverage 为 pytest/Vitest 注入项目或默认阈值；Maven/Gradle 仅认可已执行且配置足够的 JaCoCo gate，无法证明其他 runner 的 gate 时保持 `uncovered`。
- 原生 TDD completion gate 现接入实际控制器：native-v1 进入 `complete` 必须在 `ledger.tdd_trace` 保存与最终 Source Receipt、冻结风险一致且结果为 `pass` 的 Trace v4；trace 一经写入不可替换。PDLC workflow 不受该 gate 影响，第三方 TDD stage provider 仍受 native workflow gate 约束。高风险绿灯增加至三次，金额/支付增加 property 场景；coverage 识别 Rust `--fail-under` 与 .NET `/p:Threshold` 的显式阈值。
- 新增轻量 TDD/Impact Trace 门禁：每条运行时验收项绑定测试标识、真实红绿命令回执和正常/边界/异常场景；冻结风险确定性要求权限、并发、幂等、事务、数据访问、契约、安全或敏感数据覆盖，并把改动入口及关联调用链绑定到最终回归测试。trace 不新增持久状态，缺少证据统一标为 `uncovered`。
- PDLC workflow provider 改按稳定 Skill 路径、阶段完整性和任务语义兼容后续升级；新任务可接受兼容的内容变化，已冻结任务继续用逐文件指纹阻止运行中途漂移。
- Superpowers 与 Matt Pocock 的 TDD adapter 同步改为按稳定入口与 TDD 语义兼容升级；已冻结 TDD 阶段仍拒绝中途替换 Skill 内容。
- 明确日常交付的验证、测试与变更记录纪律：不可运行的检查和未证实范围保持 `uncovered`；运行时功能与修复必须把验收项映射为覆盖正常、边界和异常行为的测试，并按风险加入权限、并发或幂等场景；目标项目的写入任务必须更新对应 changelog，不存在时在项目根目录创建，并只记录当前任务变更。
- 加固文字分步交付：触发“逐步修复 / 分步执行 / 按计划一步步做”后，每步开始与结果必须使用独立 commentary，完成消息不得合并下一步开始；原生计划面板不可用不豁免文字分步。分步轨迹升级为 v2，以评估者记录的唯一 `message_ref` 拒绝把多个可见步骤状态伪装成独立消息；v1 旧轨迹仅兼容读取并保持 `uncovered`。
- 修复分步进度的一致性：计划投影覆盖 closure/autonomy 修复阶段，阻塞项停止显示进行中且保留冻结步骤名称，阻塞原因由文字终态报告表达，未知阶段明确拒绝；运行时不承诺不存在动作与回执的终态原生同步。轨迹可复用持久降级证据，在工具重连和恢复后继续 text；原生回执关联完整步骤投影，拒绝同一引用的矛盾状态，允许真实合并更新，缺少投影的旧轨迹保持 `uncovered`。补充状态、停止、恢复与 CLI 行为回归。
- 打通原生计划同步失败后的文字降级：持久状态允许携带观测与告知引用的单向 `native → text` 转换，独立 revision 清除原生确认，恢复后继续业务而不重复同步；保留既有 lease、阶段及验收门禁。轨迹检查器同步接受有据降级后的持续文字进度，缺少调用回执仍为 `uncovered`，首次跳过可用工具仍失败；补充持久写入、恢复和 CLI 回归。
- 修正“分步显示”与文字汇报混淆：执行前核对当前原生计划工具，可用时实际调用并检查回执；缺失、未知或调用失败时明确告知文字降级并逐项展示状态。计划文件、投影 JSON 和 commentary 不能冒充原生面板；离线轨迹另校验同步与降级观测，缺失证据标为 `uncovered`，不声称已验证 UI 渲染。
- 修复本地 runner 输出读取线程或进度回调异常未传回主流程的问题：Codex、Claude 均清场并返回 `unknown`，不再将部分回答交付为成功结果。
- 收紧 CLI 原生派发边界：Codex 覆盖 agents 与 multi-agent feature 开关，Claude 禁用 Agent/Task/TeamCreate；保留读取、编辑和验证工具，明确该边界不替代 shell/MCP 外部服务权限治理。
- 新增离线分步轨迹检查及六个回归场景，覆盖结果隐藏、下一步抢跑、失败停止和恢复重做，并接入全量检查；区分 fixture/evaluator-attested，缺少轨迹或真实宿主发布证据仍标为 `uncovered`。
- 补充分步可见交付规则：用户要求“逐步修复 / 分步执行 / 按计划一步步做”时，先展示步骤清单，每步开始说明目标和范围，结束展示改动、验证结果和进度，再进入下一步；没有宿主计划工具时使用文本清单。已授权且无阻塞时自动继续，只有用户要求逐步确认或遇到既有决策门禁才暂停；恢复时不为补展示重做已完成工作。
- 修复 Codex、Claude 共享 runner 在主进程正常或非零退出后遗留后台写入的问题：退出前终止本次进程组内的残留子进程，清理权限异常返回 `unknown`；不把此边界扩展为对脱离原进程组或宿主外部服务的清理保证。
- 收紧 Git 代码评测的报告比较：拒绝缺失、重复或集合不一致的任务结果，以及与结果矛盾的状态、模式和摘要；保留完整失败报告及旧报告缺少整题耗时的兼容处理。说明 single/multi 仅测量单写入及追加只读审查的执行情况和耗时，不能据此宣称提高修复成功率。
- 多模型 runner receipt 升级为 v2：本地 CLI 只声明冻结的 `requested` 模型，provider 返回且匹配模型时才标为 `observed`；usage 仅接受 provider 回执，不再将请求参数或估算当作事实。
- 新增 `multi_model_smoke.py`：默认只计划；显式 `--allow-execute` 后在 detached 临时 Git worktree 中运行一个只读 scout，并输出不含 prompt 或原始回答的脱敏 receipt。临时 worktree 会在成功、失败或超时后清理。
- 新增 `multi_model_repo_eval.py` 与两题冻结 Git 代码任务：默认只计划；显式执行时在内部临时仓库中比较 single/multi 拓扑。通过结论由固定 unittest 与模型改动范围决定；multi 只有在两项通过后追加只读 reviewer。
- 修复安装完整性漏检：`install.sh` 将 `scripts/capsule_dispatch.py` 纳入运行时必需文件；源码副本缺失该脚本时安装会明确失败，不再生成表面成功、实际无法投递 successor task 的 Skill 链接。
- 为上述安装边界补充回归测试，覆盖缺少 Capsule Dispatch 脚本的隔离源码安装失败场景。
- 稳定安装文档现在固定指向已发布的 `v0.1.0` tag，并使用 `--release 0.1.0`；需要跟随开发分支时必须显式传入 `--latest`，避免无意安装浮动的 `main`。
- 修复完整检查的解释器漂移：移除 `uv` 路径中硬编码的 Python 3.13；系统 `python3` 不具备 PyYAML 时，改为使用项目 `.venv`，并明确提示创建 Python 3.9+ 虚拟环境。
- 新增 GitHub Actions 质量门禁：PR、推送至 `main` 和 `v*` tag 均安装开发依赖并执行 `bash scripts/check.sh --full`。
- 精简 README：移除重复的协议、状态命令和调度细节，保留快速开始、入口选择、安装来源与授权边界，并链接到对应的权威参考文档。

## [0.1.0] - 2026-09-04

- 安装器现在支持 `--latest`、`--release <version>` 与 `--tag <tag>` 三种远程来源选择；release 版本确定性映射到 `v<version>` tag，tag 安装/升级均使用精确 ref。`--source` 不能与远程选择混用；同时修复帮助文本中的 Markdown 反引号被 Shell 误执行的问题。
- 新增 Capsule Dispatch v1：Codex CLI 与 Claude Code 可将冻结 capsule 幂等投递到独立 successor task，并以 `delivered | unavailable | failed | indeterminate` 回执区分创建结果；回执校验稳定 task id、非空失败原因和 schema，崩溃恢复会持久化 `indeterminate`，绝不自动重派。ChatGPT Desktop 当前缺少强制 leaf 能力，原生 child 保持 `unavailable`，不进入 worker lifecycle 或 Batch receipt。
- 收紧 Single State native worker registry：拒绝未登记角色、`reviewer` 与历史别名；普通 worker 必须由 `delegated` 路由授权，并且登记、清场与 complete 均要求同会话 `host_observed` tree-query 证据。normal/high review 只接受冻结 external runner 的 Review v3 role result。
- 默认 Provider 选择不再预加载 snapshot controller；snapshot identity 仅在持久 state 操作时加载，并补充子进程回归测试与成本边界场景。
- 自治状态契约从 core controller 提取为仅 schema 11 按需加载的扩展模块；自治快照显式冻结该模块，core 快照不再携带它。
- 修复计划与恢复路径的两处指令/隔离偏差：`converge-plan` 仅负责可执行 Plan，简单同会话任务明确走根入口 `inline`，所有进入该 Skill 的 Plan 都读取并校验 Plan Contract；`delivery_state list/doctor` 现在只读取当前 workspace 与其 Git common-dir 的状态目录，不再因其他 workspace 的损坏 state 返回错误恢复结果。
- 修复 Stop Hook 的跨 workspace 误阻断：状态扫描现在按当前 workspace 的既有 SHA-256 状态目录隔离；其他 workspace 的损坏状态不会阻塞无关任务，本 workspace 的损坏状态仍安全阻断并给出恢复诊断。自治冻结评测新增该隔离场景。Skill 入口同时要求按已选路径逐份读取引用，避免一次拼接多个完整协议造成不必要的上下文压力。
- 修复自治扩展与配置交付边界：安装器现校验两个扩展的调用策略文件；service run 在持久化状态后主动唤醒 LaunchAgent，唤醒失败会先将状态收束为 `blocked/no_progress` 再释放 lease；LaunchAgent 使用安装时的 Python 解释器，不再依赖固定的 `/usr/bin/python3`。Stop Hook 与 LaunchAgent 配置行为现都进入冻结自治评测题库与快照，补齐安装、状态清场和配置回归测试。
- 默认安装现在注册全部七个 Skill，改善宿主发现与显式调用；注册不会安装自治 Stop Hook、启动 service 或执行模型。自治 Hook 仍仅由 `--autonomy` 显式启用，多模型仍仅按用户明确请求执行；doctor 和安装预检同步校验七个入口。
- 修复核心 + 按需扩展的五个边界缺口：扩展卸载仅移除对应 Skill/Hook，不再连带删除核心 Suite；v16 `extended` 快照经唯一映射得到 `multimodel + autonomy`；扩展文件改为显式归属；全量收口的 CodeGraph 收据必须使用由冻结 scope 与 closure matrix 确定生成的查询；Hook 自治不再冻结多模型，service 才显式选择它。同步补齐回归测试与安装/源码 checkout 边界说明。
- 全量收口图谱回执现在只接受实际执行的 `codegraph` 查询；移除尚无可执行查询契约的 `codebase-memory-mcp` 放行，避免版本查询或伪造工具名冒充影响面证据。
- Controller Snapshot 协议升级为 v17：默认只冻结核心控制面；`autonomy` 与 `multimodel` 是闭合、显式声明的扩展集合，descriptor 与非快照 controller identity 均绑定同一集合，不再存在 `core`/`extended` profile 旁路。自治依赖自动带入多模型执行集合。
- 新增可选的 `converge-autonomy` 与 `converge-multimodel` Skill 入口；安装器仅在 `--autonomy`/`--autonomy-service` 或 `--multimodel` 时暴露对应扩展，普通安装保持核心 Suite。
- `scripts/check.sh` 默认不再重复执行完整自治轨迹，只运行快速契约集；`--full` 与 `autonomous_delivery_eval.py --execute` 仍执行完整 47 场景评测，发布前可显式使用。补齐相应命令行、快照和回归测试。
- 删除已停用的 `fast_path` 实现及其测试、安装和文档引用；doctor 现在实际探测并报告 CodeGraph 可用性，避免仅根据命令存在与否误报。
- 调整根 `SKILL.md` 的可读性契约：移除 2700B 的静态字节上限，恢复完整、自然的路由和自治说明；继续以行为、引用和完整检查验证功能，不用压缩措辞换取测试通过。
- 闭环修复全量收口 Plan binding：closure gate 现精确绑定 routing 的需求摘要、state baseline 的 commit/diff identity 和允许范围；矩阵必须真正覆盖而非仅与 scope 相交，Plan task 不得越出 scope。complete 会在当前 workspace 重跑并要求 Plan audit 覆盖 state acceptance，缺 audit、未完成或旧源码证据一律拒绝；图谱回执改为绑定当前源码上的 observed `codegraph` Evidence Receipt，不再接受自填输出 hash。
- 修复 Plan v6 审计与 Provider 冻结的两条旁路：task source chain 的最终 receipt 必须等于真实 workspace Source Receipt，不能以自洽但脱离实际源码的 `source_after` 结束；全量收口 Plan 的每个 task Provider Binding 必须精确匹配 state Binding，不能在 closure 时切换 Provider 选择或理由。
- 修复全量收口的通用状态旁路：所有 `full_closure_required` 状态的 closure gate 现在必须携带并通过完整 Plan v6，且 Plan baseline 与 state 一致、closure matrix 覆盖冻结 scope；恢复和非自治路径不能再只凭 review gate 绕过矩阵审计。
- 修复全量收口与跨服务自治入口：`autonomy_begin --full-closure` 现明确拒绝并要求先走 Plan v6 closure matrix，避免无计划状态绕过矩阵审计；跨服务路由的 integration review budget 改由冻结路由派生。`task_profile.py` 分类 CLI 移除无效 `--request-file`，文档改为由持久化 `freeze_routing` 绑定原始请求摘要。
- 修复自治闭环的路由与 Provider 冻结偏差：`autonomy_begin` 现冻结 `auto|pdlc|native` 的实际 Provider Binding 和 `feature|fix|refactor` 类型，并按 Provider 选择正确起始阶段；未提供冻结任务画像时按高不确定性保守进入 planned，显式画像与路径/语义风险合并后写入 Routing Receipt。全量收口改为控制器显式 `--full-closure` 决策，不再从原始请求关键词猜测；task lease identity 同时绑定 requirements，避免不同目标发生跨 worktree 冲突。
- 新增有界终态 closure gate：全量收口任务在 `verify-final` 后确定性进入 `closure-review`，gate 必须绑定当前源码、冻结范围、图谱回执与独立 blind Review v3 closure request 才能 complete；首次 finding 最多修复一次并作一次最终复核，第三次 closure 或最终仍有 finding 明确 blocked/uncovered，禁止无限修复循环。
- 修复“全量收口”请求在状态恢复时丢失的路由旁路：Routing Receipt 升级为 v3，冻结原始请求 SHA-256 与 `full_closure_required`，两者纳入回执指纹并在每次恢复、范围和终态校验时重算；`autonomy_begin` 同样接收 `--request-file`，不会再把已声明的“全部/彻底”任务降回空请求的 inline 路径。Plan v6 的 closure matrix 升级为内层 v3：图谱回执绑定基线 Source Receipt 与每条链的 `id/entrypoints/callers` 投影，改动入口或调用面必须重新出具回执。
- 修复“局部全绿即全量完成”的收口缺口：用户要求“全部/所有/深度审查/彻底/不留遗漏”时，Converge 现在必须先冻结有限影响面矩阵，将输入、冻结、副作用、回执与恢复逐格映射到既有 task/final acceptance 的新鲜证据；未覆盖项明确为 `uncovered`，不得再宣称“全部完成”或“没有其他问题”。复用 Plan v6 completion audit，不新增第二状态机或无界复查循环。
- 将收口矩阵升级为 Plan Contract v6 的强制结构，而非文字约定：所有计划必须逐链声明 input/freeze/effect/receipt/recovery，`covered`/`not_applicable` 均绑定既有 final acceptance，`uncovered` 使 `plan_check audit --require-complete` 确定性失败；v5 和更早计划直接拒绝。
- 加固收口矩阵 v2：每条链必须列出 workspace entrypoint 与 caller，entrypoint 必须覆盖全部 `owned_paths`；audit 再用实际最终 diff 检查 `closure_scope_drift`，防止只写泛化主链或漏列实际改动入口。
- 补齐外部 Review/runner 的同链路遗漏：Review request 现同时绑定当前 ledger acceptance 和 frozen allowed scope；blind review 不再拼入调用者的实现上下文；本地 runner 在持久化 launch 前先校验冻结命令，配置漂移不会留下不可重派的未知 launch。Review adapter 改从 `--request-file` 读取完整 request，并为外部输入增加有界限制。
- 修复外部 Review 证据链和 Codex 配置漂移：每个 canonical Review v3 request 现完整冻结在对应 launch，模型输出先经 adapter 规范化为同一条 Review v3 record，再作为已绑定 reviewer role result 写入 receipt；完成门禁要求该 record 与当前 state request 完全相同，不能再由泛化 `findings/next_action` 代替。lifecycle 改从 `--review-request-file` / `--review-requests-file` 读取 request，避免验收与范围随命令行参数暴露。Codex leaf launch 额外冻结 `$CODEX_HOME/config.toml` 内容指纹，计划后配置改变会在启动前明确阻断。
- 修复外部 Codex reviewer 的配置与完成闭环：leaf runner 恢复读取用户 `$CODEX_HOME/config.toml`，冻结 model/effort/sandbox 仍覆盖可变默认值；external reviewer 不再伪装为 host worker，而是以冻结 `profile.worker_id`、同一 request binding 与 completed role result 作为独立外部证据身份。runner lifecycle 现要求完整 canonical Review v3 request，调用既有 adapter 重算 fingerprint 并在外部调用前校验当前 task、baseline 与源码；fan-out reviewer 缺少请求或请求不匹配时不再写入 launch、不产生模型调用。
- 修复 Review 与自治完成的剩余旁路：runner lifecycle 现可将冻结 `review_request_fingerprint` 贯通到 Codex、Claude 与 OpenAI-compatible launch，并拒绝非 reviewer 伪绑定；自治 complete 必须有 committed action，audit batch 与具体 Evidence Receipt 指纹绑定，service 同时校验冻结 `audit_argv`；没有 lease root 的 active Gate 不再返回可执行 continuation。
- 加固自治 service 与 Review 完成门禁：同一 managed state 的 service 推进改为非阻塞互斥，竞争调用明确返回 `busy`；过期或非所属 lease 会在 Hook/Service 排队或执行前阻断，需人工恢复的 service state 只诊断一次后退出，不再无限重试。自治完成必须保存与当前源码绑定的 audit Evidence Receipt；Review pass 必须同时具备绑定同一 `review_request_fingerprint` 的已完成 reviewer role result。Review adapter 现保留 `blocked_reason`，并补齐上述回归测试与使用契约。
- 新增显式自治交付与可选低风险持久 service：冻结单步 action、独立 verifier/audit、runner launch/result 回执与有限 cycle budget；修复初始化与终态 lease 清场、无效 service state 隔离、Hook state 的 service 误处置、service 唤醒强杀、state root 错配、损坏状态 fail-open 和 metadata revision 绕过续跑上限；审计失败仍保留证据。损坏或不可读的 managed state 现输出恢复诊断，不再被 service/doctor/Hook 静默忽略。
- 修复自治计划在审计 finding、终态崩溃和服务异常中的失控：initial finding 确定性进入单次 `autonomy-repair` 后再作 final re-audit，Hook 保持 stage/action 去重但不再拦截真实阶段推进；service 仅在显式声明 `audit_findings_exit_code` 时将该退出码视为 finding，其余 audit 非零仍安全阻塞。重启扫描会幂等释放终态遗留 lease；诊断性坏 state 记录一次后成功退出，避免 LaunchAgent 无限重启。
- 修复自治 repair 与 Review v3 共用 `ledger.repair_fingerprints` 导致预算串扰：自治 repair 改用独立、append-only 的 `ledger.autonomy_repair_fingerprints`，只可在 initial finding 后的 `autonomy-repair → verify-final` 转换中消费；service repair 不再错误消耗 Review repair 预算或被状态校验阻塞。
- 修复自治 Hook 的失败收束与 service 证据缺口：Codex queue 失败、无 session 或重复 Stop 无进展时，run 现在确定性写为 `blocked/no_progress` 并释放 lease，绝不重投不确定 continuation；service 对失败 verifier 和修复后的再次 audit finding 都保留 fail Evidence Receipt。非对象 managed JSON 现与损坏 JSON 一样由 service/doctor 诊断，文档同步明确仅有诊断时 service 成功退出以避免 LaunchAgent 重启循环。
- 多模型协作改为结构化、可恢复的结果闭环：只读 scout/reviewer 只能返回与冻结 launch 绑定的受限 JSON 结论，原始模型文本不再经 lifecycle 返回或进入 ledger；完成 receipt 与结论同条原子记录，缺少结论的历史 receipt 会交接阻塞而非重派。新增 controller-owned、最多三个任务的只读 fan-out/fan-in：全部 launch 先原子持久化，再并发执行并按 task id 稳定汇总；禁止 writer、peer 消息、共享任务队列与自动重试，默认单角色和非多模型路径不变。
- 修复 fan-out 两个完成性缺口：`invalid`/`unavailable` 的只读角色结果不再满足完成门槛，必须交接阻塞；`role_dispatch.py --fanout` 与 `runner_lifecycle.py --fanout` 现为明确、可测试的 CLI 接线，不再只停留在 Python helper。
- README 将新手快速开始前置：安装、刷新、首个可复制提示词与五个 Skill 的选择表在能力总览之前；补充多模型的显式触发、默认角色分工、示例与证据边界，完整运行时示例和维护说明仍保留在后文链接。
- 补强 Skill 运行与审查闭环：文档 helper 统一从对应 Skill 根目录解析；Review v3 在不可变 round 内保留有界 `finding_records` 以支持恢复和定向复核，当前 round 的 finding 不再允许省略 records、历史 round 保持只读兼容；风险画像明确要求语义声明、路径标记仅作下限；交付 JSON 仅汇总指纹校验 runner receipt 的 `total_tokens`，不冒充远端签名，宿主未公开的工具调用和用户阻塞明确标为 unavailable。同步校准可信本地当前会话的清场规则、Review 的 fresh-context 语义及其契约回归测试。
- 明确模型事实门禁：模型自述、自然语言回执或计划文本不能替代已执行命令、结构化证据、Git/状态机结果或宿主终态；同时不把恶意篡改防护扩展为签名服务、后台守护或第二状态。
- 版本号改用 `0.0.x` 节奏：当前版本由 `0.21.0` 调整为 `0.0.21`，后续快速迭代递增末位。
- 重构可选多模型协作：以 `router`、`scout`、`specifier`、`implementer`、`verifier`、`reviewer`、`adjudicator` 七个固定角色替代固定流水线；控制器每次只选择一个下一角色。默认 Terra medium 路由/取证、Terra high 规格/审查、Luna high 实施、Sol high 裁决；`verifier` 始终由工具给出证据，只有 `implementer` 可写工作区。Codex 与 Claude Code 都经同形的受限 CLI runner：冻结 model/effort/预算，读取角色无 shell，写入限独立 worktree，并以一致的进程回执表示结果。多模型配置升级为 v4，旧 v3 直接拒绝，测试覆盖角色边界、动态选择与配置校验。
- 修复多模型外部 runner 的断链与边界表述：`runner_launch.py` 现在消费冻结 dispatch，支持显式 plan/argv/execute 路径；Codex 与 Claude 本地 receipt 都记录请求的 model/effort，但不伪称远端实际观察。统一角色权限契约为“无可写 shell”，同时明确 Codex read-only sandbox 与 Claude `Read,Grep,Glob`/CLI permission 机制不同，Claude 不再被表述为 OS sandbox。
- 多模型 agent 现通过 controller-owned `runner_lifecycle.py` 形成最小可靠闭环：先原子写入 launch，lease 外执行，再原子写入 result；未知 launch 不自动重派。local runner workspace 绑定当前 run，阻断跨任务目录。inline/tool 与非多模型路径保持不变；native transport 仅在宿主真实提供模型、worker ref 与查询能力后再接入。
- 修复受限 runner 的协作结果断链：Codex、Claude 与 OpenAI-compatible runner 统一向当前 controller 返回受输出预算约束的临时 `output`，lifecycle 只将 receipt 写入 ledger；没有可提取最终文本时明确标记 `unavailable`。控制器必须将临时文本转为既有结构化 evidence/review 后再核验，不能把模型原文或成功退出码当作状态推进依据。
- 校正轮次预算边界：Claude CLI 的 `--max-turns` 可强制冻结预算；当前 Codex CLI 无对应参数，Codex 仅由 timeout 与输出上限硬性约束，文档和回归测试不再暗示其已强制轮次限制。
- 修复本地 CLI 的 stdin 超时绕过：prompt 改为并发写入，Codex/Claude 在子进程停止读 stdin 时仍会按冻结 timeout kill/reap 并生成终态 receipt；输出上限明确为本地检测后的保守终止边界。
- 修复 PDLC Provider 仅被选中却未被实际激活的断点：新增确定性 `freeze-binding`，Plan 与 Batch 仅接受含入口/closure 来源的完整冻结 Binding；native、自动回退与 PDLC 均可据此显式调用对应 Skill，`pdlc-run` 不能替代调用，入口不可用时确定性阻塞。
- 快速开发阶段移除历史 Schema 读取/迁移：Single State 仅 v10、Runtime Binding 仅 v4、Plan 仅 v5、Batch State 仅 v4、Review 仅 Protocol v3，旧输入直接拒绝；安装器的 `--upgrade` 自动替换受管同名符号链接（不删除目录），并修正 lease 示例中的 Git common-dir 语义。
- 压缩根 `converge/SKILL.md` 至 2.7KB 内：入口仅保留范围、验证、Provider、路由、租约、审查与终态决策，条件协议下沉到既有 references；Claude Code 现在以当前会话真实的 `Agent` 与 task list 能力协商，任一缺失即确定性回退手工交接，不按安装或版本猜测。
- Codex Desktop 与 Claude Code 的原生 worker 工具现在作为可信本地宿主：automatic `controller_attested` binding 可登记、查询与清场当前会话 worker；仍要求稳定 `worker_ref`、推进前查询和派发不确定不重派。`checkpoint=cross_session` 继续要求 `host_observed` bridge，Codex CLI 仍仅是外部 leaf runner。
- 补齐 0.0.21 runner 与控制面边界：Codex leaf 忽略可变用户配置/规则、超时后回收子进程；外部 runner 拒绝空响应 ID，prompt 指纹必须是合法 SHA-256。
- Controller Snapshot 现冻结 Worker Runner 协议；Single State ledger 限定允许字段并记录 runner launch/result 的 append-only 完成门禁。停用的 generic fast path 删除遗留资格校验，仅保留确定性阻断；补充输出预算按 UTF-8 字节计量的兼容说明与回归测试。
- 0.0.21：通用 fast path 已停用；Git 空白 diff 不能证明 Markdown 等文档无语义变化，所有改动回到完整验证路径。Controller Snapshot 同时冻结 fast-path 与 runner helper。
- 新增冻结的 Worker Profile v1 与薄 Runner Registry：Codex CLI 可精确绑定 model/reasoning effort/sandbox；OpenAI-compatible runner 当前仅开放已验证的 Zhipu 无 shell、无工作区写入 leaf。真实进程或 HTTPS egress 均需调用方显式允许；runner receipt 不冒充宿主 `host_observed`。
- 修复 runner 执行边界：Codex 在执行前复核 sandbox、独立 worktree 与二进制身份，并在 stdin 异常时回收进程；外部请求固定 provider 凭据变量和 effort mapping，缺失凭据返回终态未知回执；畸形 receipt 不再能够通过完成门禁。

- 控制面一次性硬化：Runtime Binding 升级为 v4，普通 capability 协商只能得到 `controller_attested`；只有绑定完整原始宿主观察的 `bind_observed` 才可启用可观测 watchdog。当前 Codex 的 wait timeout 保持 `terminal-only`，不会因调用方声明能力或重复超时自动中断未完成子任务；中断前保留可恢复的 partial handoff。
- Runtime Action Contract 新增带精确 task/worker 身份的 `wait` 与 `interrupt`，无 wait 能力时确定性退回 query，避免生成无法执行的 watchdog 建议。Controller Protocol 升级为 v12，旧快照仅可释放自身 lease，不能绕过新的控制规则。
- Plan v5 拒绝 `TBD`、`unknown`、待定等伪 resolution；trigger eval 的 selector 指纹改为绑定 argv 与实际 artifact 内容。Eval Sample Receipt 升级为 v4，证据文件必须位于 candidate 仓库外并明确为 `evaluator_attested`，worker registry 的顺序不再影响评测结果。
- 根 Skill 对 simple inline 路径按需加载执行控制细节，减少不需要 worker/recovery 的任务上下文；补充本轮控制面设计取舍与独立前向验收记录。
- Controller Protocol 升级为 v10：冻结 Eval helper 成为可信 runner 的精确白名单入口；judge、catalog 与 evaluator 固定到修改前 Snapshot，样本绑定默认 managed state 中正式 Single State v10 的 evaluator/host-observed 清场证据，Git tree 与反斜杠/touched-path 边界按真实对象执行；v9→v10 一次性 bootstrap 必须把 locked differential 记为 uncovered。
- Plan v5 decisions 改为结构化已决记录，未决事项不能进入执行；最终 `audit --require-complete` 用退出码执行完成门禁。selector 运行错误单列并使 F1 失去满分，避免错误被统计成正常未选择。
- 新增独立自进化研究备忘；当前 Suite 不启用自动自改、后台学习或第二套记忆状态。
- 0.20 控制真实性加固：Routing Receipt v2 绑定完整任务画像、允许路径、review tier 与 integration requirement；完成门禁按真实 Git diff 阻止路由降级、范围漂移和未声明 SQL/权限等风险。
- Evidence Receipt 升级为 v2，由标准库 runner 直接执行 argv（不经 shell）并绑定退出码、输出摘要、runner、receipt 与 Source Receipt；报告强制严格证据，不再把旧回执或 controller attestation 洗成 ready。
- Review result 绑定 canonical request 的 task/验收/范围/baseline/source；repair、re-review 与 integration 预算按动作精确消费；缺少 fresh context 时自审只能给 suggestion，不能满足独立盲审门禁。
- Runtime cleanup 只有绑定原始 host tree-query observation 才标记 `host_observed`；新增按 workspace 的 state `list/doctor` 冷恢复入口。
- Eval Contract 升级为 v3，control/candidate 解析 Git commit/tree、judge 绑定文件字节、worker 绑定 host-observed registry、样本路径受 allowed scope 约束；新增真实 selector 触发 runner、混淆矩阵与 F1，执行前完整校验 case 并绑定 dataset/selector/runner 指纹，且纳入 Controller Snapshot。
- generic TDD 显式选择必须提供唯一 `--tdd-skill <exact-SKILL.md>`，删除按字典序猜选；Controller Protocol 升级为 v9，Suite 版本升级为 0.20.0。
- Review 完成闸门绑定已登记且宿主终态 completed 的 reviewer，强制 initial quality/integration 独立盲审，并阻止未消费 integration 预算或未通过结果完成。
- Eval Sample Receipt 升级为 v2，绑定真实证据文件内容；差分报告使用 control/candidate 双侧结果，exploration 单独统计且不作为 completion gate。
- generic TDD 改为仅显式选择；简单 inline 路径不再创建五阶段宿主计划，并补充精确 lease release 说明。
- 五个 Skill 增加 Git、Python 3.9+、完整 Suite 与 Codex/Claude Code 兼容性元数据；新增五入口 trigger/hard-negative eval 数据及确定性校验。

### 0.19.0

- 修复旧 Single State Schema 可绕过 v10 完成证据门禁的问题；旧状态只允许读取或原子迁移，任何新 complete 写入都要求 Source/Evidence Receipt。
- Eval Contract 升级为 v2：拒绝调用方直接声明 `samples=["pass"]`，改用绑定 scenario/control/candidate/judge/worker/source 的不可变 Sample Receipt；关键决策按每个 required scenario 校验三个 distinct worker，且确定性推导 exploration/uncovered。
- Runtime Binding/cleanup receipt 升级为 v2，宿主计划、worker 进度和清场显式区分 `host_observed` 与 `controller_attested`；交付报告只把结构化验收与检查作为已验证范围，自由文本仅作声明。
- Controller Snapshot Protocol v8 补齐实际可路由的 `converge-batch` 闭包，并只精确授权两个冻结 Batch helper；Review Contract 新增可执行 stdin CLI，doctor 明确提示显式与 AGENTS.md 隐式激活边界，同步修正 Batch Receipt v4 文档。

### 0.18.0

- 统一 Review Protocol v3 与 Single State 的内部复核记录，新增 v2 结果确定性适配器，稳定生成 SHA-256 finding 身份并校验 blocked/findings 互斥。
- 当前完成态必须绑定真实 Source Receipt v2 与每项验收的 Evidence Receipt v1；Controller Snapshot Protocol v8 冻结实际调用的 plan/review/eval 控制面。
- Codex Plan 确认改为 acknowledgement-only 写入，禁止与阶段推进混写；终态报告历史同样只能独立追加，重复报告可明确显示“无新增变化”。
- 新增可执行的差分评估 helper，按 touched control surfaces 全选历史逃逸、计算样本分布并执行最多三轮、首次无改善即停止的有限规则。
- 修复 Claude/Codex 安装清单遗漏 `converge-eval`、崩溃遗留安装锁永久阻塞、doctor 输出整段 Provider JSON 和仓库误跟踪运行时锁文件。
- 最终报告限制用户文本长度，区分验收未通过与其他待处理项，并在 Git 工作区不可读时禁止宣称“已完成，可使用”。

### 0.17.0

- Source Receipt 升级为 v2，源码身份纳入路径类型、执行权限和内容摘要；Plan Contract v5 冻结脏基线 Source Receipt，并按 task 的 before/after receipt 归属实际增量。
- Single State 升级为 v10、Review Protocol 升级为 v3：复核按不可变源码轮次追加，高风险完成态必须具备当前源码的独立 blind spec/quality 通过结论。
- 新增稳定的 Codex Plan Projection 与 `sync-plan` 动作；简单任务直接复用宿主计划，持久任务以排除确认字段的投影指纹防止同步自循环。
- 修复空 worker registry 可掩盖意外后代、当前 Snapshot release 错用 live helper、失败状态写入提前续租和终态清场旁路。
- Batch Receipt 升级为 v4，除正式 delegate state 与 Git 前序链外，继续绑定 Source Receipt v2；Controller Protocol 升级为 v7。

### 0.16.0

- 修复 20 项控制面缺陷：旧 Snapshot 不再执行冻结的历史 lease 代码；Controller Protocol 升为 v6，并共享 Source/Evidence Receipt Schema v1。
- Plan Contract v4 冻结真实 Git baseline；工作区统计和范围审计覆盖 baseline 之后的已提交、已暂存、未提交及未跟踪变更。
- Single State v9 持久化路由、评估次数、审查预算和源码指纹；worker task、清场、租约续期、终态字段与错误动作身份均收紧。
- Batch State v4 / Receipt v3 使用 repo+plan 单一状态、正式 delegate state、完整 Provider 来源和 Git 前序链；旧活动 worker 状态不再伪迁移。
- 统一 Review Protocol v2 为同一 reviewer 的两个有序单轴请求；Runtime Binding 与清场 Receipt 显式升级为 Schema v1。
- 停止跟踪 Python 字节码并增加仓库卫生回归检查，避免运行 helper 后污染工作区和累计变更统计。

### 0.15.0

- 修复 blocked 后无法回写 worker 中断结果的问题；失败状态保持 blocked，但允许后续 revision 仅登记既有 worker 的宿主终态和新鲜清场回执。
- Runtime Binding 与清场回执绑定宿主能力指纹，回执模式只能由冻结能力推导，不能由控制器自由声明。
- Batch worker 统一为 `controller-delegate`；receipt v2 必须绑定并验证完整子 Converge complete state，关闭主调度结束而子 run 未清场的漏洞。
- 终态 runtime action 强制携带任务/计划身份，并保留真实 `blocked_reason`；运行场景测试改为直接组合生产状态机，不再导入其他测试 fixture。
- 协议自修改后，旧 Controller Snapshot 仅可继续执行内容校验后的精确 lease release；其他旧协议 helper 仍严格阻塞。

### 0.14.0

- 修复 provisional 任务画像可直接触发委派、非布尔值被静默接受、未知风险遗漏和依赖任务错误委派；只有 frozen 画像能决定最终拓扑。
- Runtime Action Contract 收紧为实际使用的六类动作，并强制 dispatch/query/verify 绑定 `task_id`、block 携带原因，删除未实现的 wait/interrupt/report 动作。
- 单任务状态升级为 Schema v8、Controller Protocol v4；有 worker 的 complete 必须携带同 revision 的完整树查询或强制叶子清场回执，活动或意外后代均阻塞。
- 明确普通 worker 与 Batch `controller-delegate` 的所有权边界；已计划 capsule 在任务画像前短路，避免重复规划。
- 新增路由、动作、清场与跨 helper 组合场景回归，并纳入正式检查。
- 新增确定性任务画像与 `inline/planned/delegated/batch` 四路径路由；风险等级与执行拓扑分离，最多评估两次，不按文件数或主观分数决策。
- 单任务与 Batch next helper 默认输出统一的单动作 JSON，并提供显式 `--format legacy` 兼容模式。
- Worker 增加 `task_id/parent_ref/depth/may_dispatch` 身份，强制根控制器唯一派发和叶子执行；Runtime Adapter 只有具备完整子树查询或强制叶子能力时才允许自动委派。
- 复核改为风险驱动：低风险自检，普通任务一个 fresh reviewer，高风险一个 blind reviewer，多任务或跨服务才执行 integration review。
- `converge-eval` 的确定性场景默认一个样本，仅关键控制决策或不稳定结果使用三个样本。
- 简单写任务不创建正式 state 或 snapshot，但继续使用轻量 writer lease 保证多窗口安全。

### 0.13.0

- Suite 集成 Plan Contract v3、实现/单任务双轴审查/全局集成审查三类独立有限循环，以及 `converge-eval` 的差分、多样本和历史逃逸行为验收；根 `converge` 保持控制面，不复制 PDLC/TDD 内部阶段。
- Codex 与 Claude Code 安装、卸载、doctor 和正式检查统一注册五个 Skill，并强制校验 `converge-eval` 的契约、脚本和历史 catalog。
- 父控制器以 Git 真值展示整个工作区累计文件数、增删行和二进制文件数，明确区别于 Codex 单步角标；脏基线不伪造本任务归因。
- 最终行为报告分别展示 known acceptance、history、exploration 和 uncovered，不再把指定场景通过表述为没有任何未知问题。
- 新增职责独立的 `converge-eval`：自修改验收冻结旧版 control 与 candidate 差分，关键决策使用多个 fresh samples 并报告分布/方差，按 touched control surface 从机器 catalog 全选历史逃逸回归，分别报告 known acceptance、history、exploration 与 uncovered；规则修订最多三次且首次无改善即停止升级，不直接执行外部副作用。
- Review Protocol v2 将任务审查拆为顺序隔离的 spec 与 quality 轴，每轴限制一次修复和一次复核；重复 finding 或无进展立即阻塞，并在全部任务通过后增加一次仅覆盖跨任务风险的 integration 审查，同时保留 v1 intent、blind 和 closure 兼容读取。
- Plan Contract v3 新增垂直切片、宽重构、集成任务和单 outcome 粒度门禁；同会话多任务改为顺序执行且不要求 commit，只有显式跨会话 checkpoint 才进入 Batch 并请求本地 commit 授权。
- 修复 Controller Snapshot 中间目录仍可写、VERSION 未进入内容地址且 helper 会在校验前导入模块的问题；完整快照现递归只读，所有冻结 helper 通过 live trusted runner 验证后执行。
- 修复 Provider registry 与 Snapshot 固定清单漂移的问题；两者现在共享同一动态 manifest 清单。
- 修复通用 TDD Binding 恢复只核对指纹、不重新检查 TDD 必需词和禁止控制行为的问题。
- 修复非法 Provider manifest 输出 Python traceback 和退出码 1 的问题；现在返回结构化 `blocked/environment`、退出码 2。
- 修复最终报告从自由文本猜测待处理数量的问题；`open_issues` 规范为列表，旧无问题文本安全迁移，多项保持准确计数。
- 收紧 Runtime Adapter 为能力协商与状态规范化；父控制器直接调用宿主工具，不再生成无法执行的伪操作。
- 删除无生产调用的 Provider/PDLC 派生常量、探测函数和重复指纹实现。

### 0.12.0

- 新增共享 `provider_contract.py`：Provider Binding 完整冻结 manifest、task contract、真实入口和显式 closure；任一来源变化都会阻塞恢复。
- Provider resolver 新增 `--provider <id>` 精确选择，并固定 workflow、Superpowers、Matt Pocock、generic、Native 的 auto 顺序；PDLC 缺失时 Native 仍携带完整入口契约独立交付。
- 新增 `runtime_adapter.py`：Codex、Claude Code 和单上下文先协商实际 dispatch/query/wait/interrupt 能力，能力不足时明确手工降级。
- worker CLI 只接受 objective milestone；父控制器使用 `observe` 根据宿主 query 生成 heartbeat。新增去重中文状态视图，不显示百分比或 ETA。
- 新增不可变 Controller Snapshot：控制文件与固定 Provider registry 一并复制到目标工作区之外的内容寻址目录；快照内 resolver 可独立选择 Native/auto Provider，自修改任务继续由启动快照控制。
- 最终报告分为默认用户 summary 与条件 diagnostic；`blocked/decision` 或 `--detail` 才展示 Provider、阶段、worker 和检查诊断。
- Closure 强化：Provider source 严格绑定 kind/relative path/候选入口，Snapshot 校验内容寻址 provenance、只读与 workspace 隔离，进度去重包含宿主终态，terminal worker 禁止 wait/interrupt，文本 diagnostic 有界展示 worker/check 摘要。
- 安装清单、doctor、Skill/README/reference 契约和版本同步到 `0.12.0`。

### 0.11.0

- Provider Schema v2 统一描述 PDLC、适配 TDD、通用 TDD 和 Native；Converge 固定为 controller，执行结果冻结 workflow/stage Provider Binding。
- Plan Contract v2 支持多个独立业务切片级 Provider Run，不再把整个复杂 PDLC 计划塞进一个黑盒任务；旧 v1 只添加迁移。
- 单任务状态升级到 Schema v7：分离包版本、控制协议和 Provider Schema，旧 v5/v6 转换为 binding；包文档升级不再误阻塞恢复。
- 新增 Progress Receipt v1 和 `delivery_progress.py`：父代理展示子任务阶段、里程碑、证据和下一步，heartbeat 不计为客观进展。
- Batch preflight 新增一次性本地 commit 授权；缺失时在派发前阻塞，不扩大到 push、merge 或发布。
- 最终报告新增最多五项关键改动，默认继续隐藏 lease、fingerprint 和状态机术语。
- 自动模式可在业务写入前说明不兼容 Provider 并降级；显式或已冻结 Provider 仍严格阻塞，Native 模式不探测外部 Provider。

### 修复

- 修复合法 Provider Schema v2 manifest 仍需控制器增加 ID 特判才能被选择的问题；workflow 与 TDD stage 现按 role、capability 和 task contract 统一发现。
- 修复 Plan Provider Binding 摘要未核对、Provider Run 递归/无界约束只停留在文档，以及 Batch capsule 丢失冻结 binding 的问题。
- 修复首次 heartbeat 因客观进度为 0 被拒绝、未知 v6 controller 被迁移为当前可信身份，以及冻结计划内验证命令无法执行的问题。
- 修复旧单任务 v5 状态首次迁移时可同时推进阶段或修改 ledger 的问题；迁移现在只能增加 v6 字段并递增 revision。
- 修复单任务 complete 可忽略仍处于 Working 的本轮 worker、恢复时无法发现 controller/provider 漂移，以及已安装但未适配 PDLC 被静默视为不存在的问题。
- 修复 PDLC、reviewer、Batch、辅助分析和独立前向测试 worker 缺少统一登记与退出清场的问题（结果已返回但宿主仍 Working，或异常路径提前结束时）。
- 修复 Batch 仅凭 receipt 即可完成和派发下一批的问题（宿主 worker 尚未进入终态时）。
- 修复单任务状态可重写冻结契约、回退阶段或篡改 ledger 的问题（跨窗口回写 Schema v5 状态时）。
- 修复 Batch capsule 仅靠文字携带递归保护的问题（缺少或错配 `planned_task/plan_id/task_id` 时）。
- 修复计划完成审计信任调用者源码指纹和变更路径的问题（审计脏工作区或陈旧证据时）。
- 修复同一计划可由两个 run/window 重复调度的问题（初始化 Batch state 时）。
- 修复 watchdog/PDLC 文档把 Skill 规则写成宿主已具备能力的问题（宿主缺少计时、中断或恢复 API 时）。
- 修复 acceptance 真实回归无法落盘的问题（fresh/pass 变为 stale/fail 时归档旧 revision，而非拒绝当前事实）。
- 修复终态缺字段可绕过非对称比较的问题（complete/blocked 恢复与回写时）。
- 修复强化后的 capsule 字段让真实旧 Batch Schema v1 无法恢复的问题（先原子迁移到 state Schema v2）。
- 修复 scheduler 在 owner 已落盘而 state 未落盘时可能永久误锁的问题（两小时 TTL、续期和显式过期接管）。
- 修复 Git 文件名反斜杠被归一化为授权斜杠路径的问题（计划 scope drift 审计时）。

### 新增

- 新增单任务 Schema v6：持久化 run-scoped worker registry，冻结 Converge controller，并从 v5 执行只添加的安全迁移。
- 新增 PDLC 1.6.0 JSON adapter manifest：校验 provider id/version、feature/fix/refactor 入口、授权边界和显式传递依赖闭包；refactor 强制外部行为不变。
- `delivery_report.py` 新增 `--input -`，简单任务无需持久 state/lease 即可生成确定性报告。
- 正式检查运行四个 Skill 的官方 `quick_validate.py`；PyYAML 开发依赖锁定为 6.0.3，缺失 validator/依赖时明确失败。
- 新增 `converge-plan`：实现前生成 Plan Contract，将复杂需求拆成单结果、可验证的短任务，并根据依赖、文件范围和上下文选择当前、fresh 或顺序执行。
- 新增 `plan_check.py`：确定性校验任务 ID、依赖环、PDLC 单任务屏障和执行 wave，并对账 `DONE/PARTIAL/NOT_DONE/CHANGED`、新鲜证据及 `scope_drift`。
- 新增无响应保护：90 秒无活动软探测、180 秒无活动且无运行进程时硬中断，只恢复同一 worker/task 一次。
- 新增决策门禁与计划仲裁边界：可逆技术选择自动记录，业务/公共契约/不可逆问题一次只询问一项；普通任务不增加多 planner 开销。
- 新增 `install.sh --doctor`：只读检查 Suite 完整性、必需资源、Python/Git 和引擎选择；版本查询会明确区分完整与残缺安装。
- 新增 Codex/Claude Code Runtime Adapter 契约和 `batch_next.py`：连接中断时恢复查询原任务，派发结果不确定时阻塞而不重复派发。
- 新增 `delivery_report.py`，从已验证 Schema v5 状态确定性生成结果、交付轮、修复数和待处理数。
- 新增激活指南和可选 `AGENTS.md` 片段，增强普通实现/修复/重构请求的发现，不自动改写用户配置。
- 将单一 Skill 拆分为职责明确的 Converge Suite：`converge` 负责单任务闭环，`converge-review` 负责独立只读审查，`converge-batch` 负责长计划接力。
- 新增 Review Protocol v1：区分意图审查与全新上下文盲审，finding 绑定源码指纹，并提供只复核原问题的 closure 规则。
- 新增 Batch Protocol v1 与原子状态 helper：全量预检、最小上下文胶囊、幂等派发、结构化 receipt、暂停/恢复/停止和计划级最终验收。
- 新增 Suite 行为契约、Batch 生命周期、并发 revision、回执与安装冲突预检回归测试。
- 建立 `convergent-delivery`，提供有限阶段的需求实现、验证、复查和交接流程。
- 同时支持 Codex 与 Claude Code，并使用单一 Skill 源文件避免流程规则漂移。
- 新增 `VERSION`、`install.sh` 及安装器回归测试；支持安装、升级、卸载与版本检查。
- 新增 worktree 与任务级 writer lease，支持不同任务并行，并阻止同一 worktree 双写或同一任务重复执行。
- 新增 `delivery_engine.py` 与回归测试：按已安装或源码中的实际 PDLC Skill 能力确定性选择 `pdlc-v1` 或 `native-v1`，支持自动选择、强制 PDLC 的环境阻塞和活动任务引擎粘性。
- 状态 Schema v4 新增冻结的执行引擎和验收证据新鲜度；`complete` 必须具有至少一项新鲜、通过的验收证据。
- 新增 PDLC 路由、引擎恢复、陈旧验证、根因无进展和脏工作区压力场景。
- lease helper 改用 Python 3.9 兼容的 UTC 写法，避免系统 Python 版本较低时无法获取或续期 lease。
- 新增结果驱动的“交付回执”规范：区分可交付、需关注、需确认和环境阻塞；支持默认摘要、业务验收矩阵、单项决策卡和按需技术证明包。
- 交付回执改为按结果自适应长度：存在风险或待决事项时，必须补足当前可用行为、已验证/未验证范围、实际影响和推荐选择。
- ledger 新增增量回执信息，避免连续检查时反复输出相同的流程、命令和文件清单。
- 新增两层已适配的第三方 TDD 引擎：Superpowers 与 Matt Pocock；PDLC 不可用时按固定优先级选择，后续才尝试受预检约束的通用 TDD Skill 和内置 TDD。
- 新增紧急处理的最小证据规则；金额、数据迁移、事务/并发、权限、公共接口和发布操作仍必须执行完整验证。
- 引擎状态升级为 Schema v5：冻结 PDLC 所需 Skill 与第三方 `SKILL.md` 的内容摘要；恢复时来源缺失、替换或更新会环境阻塞，避免同名文件或更新后的规则悄然接管任务。
- 已适配 Superpowers 与 Matt Pocock TDD 提供者改为登记版本摘要校验；相似名称和措辞只能进入通用预检或回退原生流程。
- 将“闭环实现”“闭环处理”“闭环完成”加入 Skill 的可发现描述和执行模式，减少普通功能请求绕过 `converge` 的概率。

### 变更

- 版本更新为 `0.10.0`；公共 worker/watchdog 规则收敛到 `references/execution-control.md`，委托协议禁止 provider 越过业务、契约、权限、发布和不可逆决策门禁。
- 版本更新为 `0.9.2`；Batch state 升级到 Schema v3，独立前向测试默认使用一个 evaluator 在隔离临时工作区顺序执行。
- 版本更新为 `0.9.1`；Batch state 持久化 `worker_ref/recovery_count`，Plan audit 使用真实 Git workspace 的结构化 source receipt。

- Suite 扩展为四个职责互斥的 Skill；PDLC 仍以唯一 fresh `pdlc-run` 整体委托，`planned_task=true` 阻止子执行者递归规划。
- 安装、卸载、doctor、README 和使用指南统一升级到 `0.9.0`，一次交付全部计划化执行能力。
- `converge` 收敛为单任务控制面，不再承担普通只读 review 或多 Batch 调度；高风险任务显式委托 `converge-review`。
- 安装器一次预检并安装/卸载四个 Skill；发生任一入口冲突时保留原安装和旧版入口，不产生半迁移状态。
- 安装前校验四个 Skill 的必需协议与 helper；Batch 仅允许 active 计划的当前批次派发，receipt 必须解析到当前 clean worktree 中的真实 Git commit/tree。
- 默认交付回执在简洁结果之外保留交付轮数、修复问题数和待处理项数，减少术语同时避免信息过少。
- Skill 正式名称从 `convergent-delivery` 调整为更易记的 `converge`；安装器会安全迁移指向同一源码的旧软链接。
- 状态 Schema 先升级为 v3：共享跨运行时 ledger，并用 lease、writer 与 revision 保护写入和恢复。
- 状态写入改为仅接受 stdin 候选 JSON，并由脚本推导正式路径，避免 `/tmp` 或任意路径成为恢复状态。
- `converge` 明确成为控制平面：兼容 PDLC 存在时，PDLC 独占需求产物、TDD、实现和阶段评审；`converge` 只负责范围、有限循环、lease、跨服务验收和最终报告。
- 只有 PDLC 不可用或用户明确选择原生模式时，才执行内置 TDD、语义复查和风险复查，避免双循环与重复状态机。
- 第三方 TDD 提供者改为冻结的适配引擎：只承担一次红绿实现阶段，状态、循环、复查、最终验证和报告仍由 `converge` 统一控制。
- 第三方 TDD 委托改为先读取状态中冻结的 Skill，仅采用测试设计方法，忽略其中的发布、删除、安装、worktree、外部命令和循环控制指令。
- 最终报告新增执行引擎、选择原因和验收证据新鲜度；陈旧、未知或未覆盖的检查不能宣称完成。
- 最终回复改为面向用户的摘要，不再强制输出内部状态机字段；存在待确认业务选择时，禁止把用户结论写成“已完成”。

### 文档

- 补充 PDLC / 原生引擎职责边界、选择规则、恢复策略和能力探测方式。
