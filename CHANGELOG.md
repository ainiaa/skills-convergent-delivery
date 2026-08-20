# 变更日志

本项目的重要变更记录在此文件中，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 修复

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
