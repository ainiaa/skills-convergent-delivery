<!-- PDLC-TRACE -->
<!-- 功能ID: F20260907-converge-evidence-topology -->
<!-- 功能名称: converge-evidence-topology -->
<!-- 阶段: plan -->
<!-- 创建时间: 2026-09-07 -->

# Converge 证据与执行拓扑优化计划

作者：Jeff.Liu

## 复盘结论

本轮已验证的约束规则和完整回归均有价值，但它们没有直接证明模型在真实宿主中的交互行为。反复出现新问题的原因不是单个规则遗漏，而是每轮只验证了一层：

1. 交互 smoke 只有单条提示，没有前置代码状态、已决事项或多轮会话，不能重放“审查后闭环”和“不重复提问”。
2. Desktop task、内部 subagent、CLI session 和 worktree 被混为一种执行手段；不同手段的可见性、可寻址性和恢复能力不同。
3. Desktop worktree task 的临时 ID 不等于创建失败；`list_threads` 不能作为创建确认。CLI JSONL 可确认正式 ID，但不保证 Desktop 侧栏可见。
4. 同仓库是否并发不应由“文件数”或“想并行”决定，而应由冻结的写入范围、依赖、验证和集成责任决定。

本计划不承诺由 Skill 强制宿主选择、模型必然遵守或 Desktop 自动补齐 lifecycle API。

## 目标与边界

目标是在不增加无界后台循环、平行状态真源或默认多代理的前提下，使 Converge 的关键行为可重放、执行拓扑可解释、宿主能力缺失不再被误判。

- 默认：当前 Desktop task、单 writer、同一 worktree、顺序推进。
- 同仓库并发只在计划证明写入隔离、验证隔离且有集成人时启用；每个 writer 使用独立 worktree。
- Desktop task 负责用户可见与接管；subagent 只做短暂的只读辅助；CLI runner 仅在用户明确选择可靠后台执行时使用。
- 不读取内部 session 索引作为产品能力；Desktop 临时 ID 无法正式解析时保持 `uncovered`。
- 不新增模型 judge、外部服务或自动化发布。

## 执行批次

### B1：将关键交互 smoke 改为可重放 transcript

修改 `evals/converge-interaction-v1.json` 及其校验器，场景包含：

- 冻结基线和受控初始 diff；
- 一组有顺序的 `turns`，而不是单一 prompt；
- 已决事项的具体内容；
- 每轮可观察 oracle：允许写入、禁止重复提问、所需验证、可接受终态；
- 宿主 smoke receipt 的最小字段：正式 task/session ID、基线、工作区策略、实际命令/输出摘要、观察结论和 `uncovered` 原因。

关键场景固定为局部修复、审查后同范围闭环、已决事项不重问。校验器拒绝缺 setup、单轮伪造同会话语义、缺 oracle、错误基线和不完整 receipt。

验收：构造错误 transcript 和错误 receipt 时先失败；合法 fixture 通过；真实 smoke 结果可由外部 task 复核但不由本地测试伪造。

### B2：冻结执行拓扑，而不是默认创建 worktree

为 `planned` 路由新增简短的 execution-topology contract，作为计划的组成部分，而非为 `inline` 新增状态：

| 条件 | 决策 |
|---|---|
| 单 writer 或任务依赖、范围/验证未知 | 当前 worktree 顺序执行 |
| 只读研究或审查 | subagent，可共享工作区但禁止写入 |
| 同仓库并发写入 | 必须证明路径、公共契约、配置、测试基础设施和验证均隔离；独立 worktree；指定集成人和联合验证 |
| 独立项目 | 单独 Desktop task 或明确的 CLI runner |

计划校验器拒绝：同一工作区并发 writer、缺集成人、缺联合验证、或仅用自然语言宣称“互不影响”的并行计划。

验收：覆盖顺序、只读、有效并行和四种无效并行计划的确定性测试。

### B3：明确宿主能力与用户可见性

新增短的能力矩阵并收紧根入口措辞：

- Desktop worktree task：可由用户观察和接管；创建确认只接受正式 `threadId`；临时 ID 未解析时为 `uncovered`。
- CLI JSONL runner：可取得正式 ID、记录 JSONL、按 ID 续跑；不承诺 Desktop 侧栏可见。
- CLI runner 若被显式选择，必须产生用户可打开的结构化进度日志和终态回执；不把 detached process 当成可见进度。

不实现依赖内部索引的映射，也不伪造 Desktop task 进度。向宿主提交的能力需求固定为：创建操作 ID、状态轮询、正式 ID 解析和取消。

验收：模拟 JSONL 的启动、终态、超时和无进展；Desktop 能力缺失只产生 `uncovered`，不会重发或宣称失败。

### B4：收紧入口与渐进披露

将简单任务所需的红绿与报告规则从完整 provider/coverage 细节中分离。根入口只选择：当前 task、Desktop 可见隔离 task、或用户显式 CLI runner；不从“任务复杂”自动推导后台或 worktree。

行为改动的 Eval 指令改为先运行 deterministic preflight；没有冻结 control/candidate/judge 时报告模型行为 `uncovered`，不要求必然失败的默认模型 Eval。

验收：简单 inline 不加载 runner/多代理/完整 Provider 细节；不同执行模式需要显式、可检查的选择理由。

### B5：按证据闭环，不按文案闭环

每批只做一次独立审查和一次修复复核。完成报告分开列出：确定性回归、真实宿主 smoke、尚未覆盖的宿主能力。不得因全量测试通过而扩大真实模型行为结论。

验收：`bash scripts/check.sh --full`、新增定向反例、真实 transcript smoke；每一项均绑定当前基线和结果回执。

## 顺序与停止条件

按 B1 → B2 → B3 → B4 → B5 执行。B1 未完成时不扩大模型行为结论；B2 未完成时不启用同仓库并发写入；B3 缺宿主 API 时停止在 `uncovered`，不以内部索引绕过；任一批次没有新增证据或出现同一失败两次时停止并报告阻塞。

## 不做的内容

- 不把每个任务拆成 Desktop task 或 subagent。
- 不为同仓库并发建立常驻调度器、自动合并器或第二套状态库。
- 不把 CLI session 的存在说成 Desktop 侧栏可见。
- 不因 UI 缺口在 Skill 中猜测或扫描宿主内部状态。
