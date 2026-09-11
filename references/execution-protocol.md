# 原生单任务执行协议

## 当前会话交互

同一会话的已授权写入范围在执行期间持续有效。审查检查点本身只读；结束后，in-scope finding 必须自动进入本轮修复和验证。只有用户明确“仅审查/不要修改”、停止、取消，或 finding 超出冻结范围时才暂停写入。

每个 finding 只能是 `in_scope_fix`、`blocked_decision` 或 `out_of_scope_record`。前者修复并回归；第二类一次提出推荐和决定；第三类记录影响但不扩大范围。已有决定不重复询问。没有本轮真实验证的验收不得称完成。

## 引用输入门禁

用户明确指定为实现依据的引用（包括 `codex://`、宿主附件、PR 和指定文件）是需求真源。控制器在首次业务写入前必须通过当前宿主实际读取，并据此冻结范围与验收；不得未读参考就猜测实现，或用另一套行为替代。引用未规定的内部细节沿用项目既有模式作最小选择；仅当该引用对完成需求必需但不可访问或内容不完整时阻塞。普通背景链接不构成门禁，也不要求 receipt 或内容指纹。持久化任务记录精确 reference 与读取结果，`inline` 任务在交付中说明已读取；不得用 URL、标题、模型记忆或用户转述代替读取。

参考涉及状态机、公共 API 或跨服务协作时，读取后、首次写入前先冻结行为矩阵：逐项列出输入/状态、输出、共享副作用、已知 caller 和验证方式。状态映射、重试或错误语义仍有多个合理答案时是业务决策，先询问一个推荐选项；不得根据相似实现猜测或以实现后再改的方式消歧。

外部 CLI implementer 在启动前还必须接收一个 `reference_receipt.py` 校验通过的回执：它显式列出实现依据（可为空）、每项实际读取结果和读取内容指纹；任一声明引用为 `unavailable` 或回执被篡改都会阻止 launch。launch 只保存该回执指纹，避免把引用正文或宿主敏感内容写入 runner ledger。

引用同一项目内的另一功能时，回执还必须将每个 target 绑定到明确 reference、`mirror`/`analogy`/`negative` 关系和行为矩阵。每行均写明输入、状态、输出、副作用、已知 caller 与验证方式；引用必须实际读取。缺少映射或存在多个业务语义时先进入 `blocked` 决策，绝不把项目级相似性当作自动复制许可。

一次性 `inline` 任务不落盘。仅在工作需要跨轮修复或进入 `active/blocked` 时，创建/恢复 `work_item.py` 的功能级事项；其 contract 冻结 workspace、baseline、target、requirements、acceptance、decisions 与 reference receipt。恢复只接受这些值全部相同的唯一事项；同功能事项的基线或语义 contract 不同则 `blocked`，而不是复用、迁移或选择看似最接近的项目记录。事项状态经既有 writer lease 私有写入，终态不得作为续接候选。

已落盘事项只能以 `work_item.py verify` 在其冻结的 workspace/baseline 运行验证命令，禁止直接运行该 argv 或代入其他事项的起点。它先调用 gate，再使用 `evidence_contract` 生成 observed Evidence Receipt；失败回执在同一受控调用中写入。相同源码和命令只能失败一次，gate 随后必须以退出码 2 返回 `identical_verifier_failure`，不得重复消耗重试。只有源码/argv 改变，或以 `--recovery-receipt` 提供同一源码上的 observed `pass` 回执，才允许再次运行；恢复回执不是完成证据，最终仍由既有 fresh `pass` 门禁决定。

同一用户 task 内可以依次执行构建、复审、修复和最终复核，但 Stop Hook 不得排队 successor task 或产生无用户消息的额外 task turn。执行者必须在当前 task 内消耗完有限预算并给出一个最终结果；提前停止的 active run 以 `no_progress` 终止并释放 writer lease。

仅当 workflow provider 为 `native-v1` 时读取；可选第三方 TDD provider 只替换 Build 的红绿方法。PDLC workflow 不得映射到这些阶段。

## 状态机

低风险：`scope → build → semantic-review → verify-final → complete`

高风险：`scope → build → semantic-review → verify-round-1 → independent-risk-review → finding-closure → verify-final → complete`

状态只向前推进，不递归重跑通用审查。

## Scope

- 阅读调用链、已有测试、接口和文档。
- 将每条验收项映射到公共 seam（API、Service 契约、消息或持久化边界）的测试/检查，并列出改动入口及已知 caller、共享副作用或外部契约；有 CodeGraph 时先查实际调用链。每个测试验证一个可观察行为，mock 只位于外部系统边界。
- Bug 必须先复现，记录观察、数据流、一个明确根因假设和能区分该假设的最小检查；根因不明时不改生产代码。

## Build

1. 先写或更新测试并运行，红灯必须因目标行为缺失而失败；编译、Mock 或环境错误不是有效红灯。已知 runner 使用其 runner selector 语法。
2. 只做最小实现使其变绿，不夹带重构和顺手修改。
3. 用 `evidence_contract.py run` 运行定向验证，保留 observed Evidence Receipt；无风险每个绿灯定向重跑一次，任一冻结风险重跑两次，并在最终源码上运行由 impacts 派生的 CodeGraph 查询；未索引或不可用时写入 graph `uncovered`。先以 `native_tdd_policy.py resolve --workspace <workspace>` 解析 coverage：pytest/Vitest 可注入 `quality-targets.yml` 或默认 >=85%，Rust `--fail-under`、.NET `/p:Threshold` 等显式 argv gate 可识别，其他命令须已有可证明 gate。高风险补一条 integration/contract mutation 检查；金额和支付补 property 场景，time、timezone 和不可逆操作补相应 integration 场景。所有 argv 不得携带 secret、token、password 或 key。native-v1 将通过 `tdd_impact_guard.py validate` 的 trace 保存为 `ledger.tdd_trace_candidate`，普通、Hook 和 service run 共用此候选；在进入 complete 前以当前源码候选执行 `tdd_impact_guard.py rerun --input - --workspace <workspace> --baseline <commit> --native-coverage`；每条冻结命令默认最多运行 600 秒，可用 `--timeout-seconds <0..3600>` 调整，超时阻止完成。重跑成功后在同一 complete revision 中将 stdout 的刷新 trace 固化为 `ledger.tdd_trace` 并删除候选；正式 Trace 写入后不可替换，complete 门禁会再次校验。无法确认、生成工件改变源码或没有可执行工具时标为 `uncovered`。按 [TDD 追溯](tdd-providers.md#tddimpact-trace-v5) 校验测试、风险与影响链回执。

第三方 TDD 只承担这一次红绿阶段，不得创建第二套状态、循环、worktree、发布或删除文件。

## Semantic review

只检查需求完整性、公共契约、数据映射、边界和错误响应。按根因聚合为一批，最多修复一次；修复后重跑受影响检查。

测试失败时只分类一次：真实回归/无法判断则撤回当前修复批并停止；已授权行为变化导致旧测试过期则同批更新；环境问题进入环境阻塞。

## Independent risk review

高风险时将冻结的最小材料交给全新 reviewer。返回结果必须符合 Review Protocol v3，并且 `source_fingerprint` 与当前源码一致；同一 reviewer 先完成 `spec` 单轴请求，通过后才接收 `quality` 单轴请求。旧 v2 结果直接拒绝，reviewer 必须返回有效 v3 结果。PDLC 已有 review 作为意图审查，不再重复；只增加需要的新鲜盲审。

## Finding closure

复核以历史 finding 绑定修复对象，但覆盖始终是冻结验收、当前 diff 与修复影响面；可以发现新的同范围 finding。所有 finding 按根因聚合进当前修复批，最多再消耗一次冻结的修复/复核预算；预算耗尽、重复 finding 或无客观进展立即 blocked。不得通过重新排队 successor task 或以无用户消息开启新 task turn 来扩大循环。

## Final verification

- 每次代码修改后重跑受影响检查；最终按风险执行模块或全量检查，并重跑 TDD trace 绑定的影响链测试。
- 相同 diff、相同范围的命令不重复跑；但最后一次修改前的结果只能作为过程证据。
- `pass`=命令运行且退出 0，`fail`=运行但失败，`unknown`=命令/环境不可用。只有新鲜 `pass` 能满足验收。
- 已有失败只有在存在变更前基线且当前定向回归通过时才能标记为 pre-existing。

## 停止条件

- 同一问题指纹修复后复现，或修复没有产生客观进展。
- 需要业务、范围、兼容、发布或不可逆选择。
- 依赖、凭据、环境或测试命令使结果无法判断。
- 有限修复预算用尽仍存在新的范围内问题。
