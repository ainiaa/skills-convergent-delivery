# 原生单任务执行协议

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
3. 用 `evidence_contract.py run` 运行定向验证，保留 observed Evidence Receipt；无风险每个绿灯定向重跑一次，任一冻结风险重跑两次，并在最终源码上运行由 impacts 派生的 CodeGraph 查询；未索引或不可用时写入 graph `uncovered`。先以 `native_tdd_policy.py resolve --workspace <workspace>` 解析 coverage：pytest/Vitest 可注入 `quality-targets.yml` 或默认 >=85%，Rust `--fail-under`、.NET `/p:Threshold` 等显式 argv gate 可识别，其他命令须已有可证明 gate。高风险补一条 integration/contract mutation 检查；金额和支付补 property 场景，time、timezone 和不可逆操作补相应 integration 场景。所有 argv 不得携带 secret、token、password 或 key。native-v1 将通过 `tdd_impact_guard.py validate` 的 trace 写入 `ledger.tdd_trace`；在进入 complete 前执行 `tdd_impact_guard.py rerun --input - --workspace <workspace> --baseline <commit> --native-coverage`，将其 stdout 写回 state，`complete` 会再次校验。无法确认、生成工件改变源码或没有可执行工具时标为 `uncovered`。按 [TDD 追溯](tdd-providers.md#tddimpact-trace-v5) 校验测试、风险与影响链回执。

第三方 TDD 只承担这一次红绿阶段，不得创建第二套状态、循环、worktree、发布或删除文件。

## Semantic review

只检查需求完整性、公共契约、数据映射、边界和错误响应。按根因聚合为一批，最多修复一次；修复后重跑受影响检查。

测试失败时只分类一次：真实回归/无法判断则撤回当前修复批并停止；已授权行为变化导致旧测试过期则同批更新；环境问题进入环境阻塞。

## Independent risk review

高风险时将冻结的最小材料交给全新 reviewer。返回结果必须符合 Review Protocol v3，并且 `source_fingerprint` 与当前源码一致；同一 reviewer 先完成 `spec` 单轴请求，通过后才接收 `quality` 单轴请求。旧 v2 结果先经确定性适配器转换。PDLC 已有 review 作为意图审查，不再重复；只增加需要的新鲜盲审。

## Finding closure

对每个已修 finding 只确认：原问题不再复现、对应检查通过、修复未越界、影响面是否扩大。除非影响面扩大，否则不再启动开放式发现。

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
