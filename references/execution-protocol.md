# 原生单任务执行协议

仅当 workflow provider 为 `native-v1` 时读取；可选第三方 TDD provider 只替换 Build 的红绿方法。PDLC workflow 不得映射到这些阶段。

## 状态机

低风险：`scope → build → semantic-review → verify-final → complete`

高风险：`scope → build → semantic-review → verify-round-1 → independent-risk-review → finding-closure → verify-final → complete`

状态只向前推进，不递归重跑通用审查。

## Scope

- 阅读调用链、已有测试、接口和文档。
- 将每条验收项映射到公共 seam（API、Service 契约、消息或持久化边界）的测试/检查。
- Bug 必须先复现，记录观察、数据流、一个明确根因假设和能区分该假设的最小检查；根因不明时不改生产代码。

## Build

1. 先写或更新测试并运行，红灯必须因目标行为缺失而失败；编译、Mock 或环境错误不是有效红灯。
2. 只做最小实现使其变绿，不夹带重构和顺手修改。
3. 运行定向验证并记录命令、退出码、时间和覆盖的验收项。

第三方 TDD 只承担这一次红绿阶段，不得创建第二套状态、循环、worktree、发布或删除文件。

## Semantic review

只检查需求完整性、公共契约、数据映射、边界和错误响应。按根因聚合为一批，最多修复一次；修复后重跑受影响检查。

测试失败时只分类一次：真实回归/无法判断则撤回当前修复批并停止；已授权行为变化导致旧测试过期则同批更新；环境问题进入环境阻塞。

## Independent risk review

高风险时将冻结的最小材料交给全新 reviewer。返回结果必须符合 Review Protocol v1，并且 `source_fingerprint` 与当前源码一致。PDLC 已有 review 作为意图审查，不再重复；只增加需要的新鲜盲审。

## Finding closure

对每个已修 finding 只确认：原问题不再复现、对应检查通过、修复未越界、影响面是否扩大。除非影响面扩大，否则不再启动开放式发现。

## Final verification

- 每次代码修改后重跑受影响检查；最终按风险执行模块或全量检查。
- 相同 diff、相同范围的命令不重复跑；但最后一次修改前的结果只能作为过程证据。
- `pass`=命令运行且退出 0，`fail`=运行但失败，`unknown`=命令/环境不可用。只有新鲜 `pass` 能满足验收。
- 已有失败只有在存在变更前基线且当前定向回归通过时才能标记为 pre-existing。

## 停止条件

- 同一问题指纹修复后复现，或修复没有产生客观进展。
- 需要业务、范围、兼容、发布或不可逆选择。
- 依赖、凭据、环境或测试命令使结果无法判断。
- 有限修复预算用尽仍存在新的范围内问题。
