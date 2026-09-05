# Task Routing Contract v3

执行拓扑与风险强度分开判断。先由控制器根据需求、调用链和真实验证方式填写任务画像，再由 `scripts/task_profile.py` 确定性选择 `inline | planned | delegated | batch`。不得按文件数或主观总分路由。

- 画像字段严格校验，布尔值不接受字符串/数字，未知风险名直接阻塞，避免拼写错误静默降级。
- 最多评估两次：需求输入后的 `provisional` 画像只给出推荐路径且固定返回 `planned`，不得派发；快速范围探查后的 `frozen` 画像才可产生最终执行路径。
- `cross_session=true` 才进入 `batch`。
- 只有存在可委托任务、上下文隔离有明确收益且任务之间不互相依赖时才进入 `delegated`。
- 跨模块、跨服务、依赖步骤、未知根因、非局部验证或多个可委托切片至少进入 `planned`。
- 高风险只提高 review/verification 强度，不单独触发代理。
- 路由冻结后只能因新证据升级；不得反复降级、重新规划或用路由扩大授权。

风险枚举与根 Skill 的审查触发器一致：金额/支付、时间/时区、SQL/Mapper、数据库迁移、事务、并发、幂等、公共 API、安全/权限、敏感日志、跨服务、发布契约及不可逆操作。`risk_flags` 是控制器在冻结前按需求、调用链和行为语义作出的**语义风险声明**：即使文件名普通，也必须列出金额、权限、公共兼容等受影响语义；不能等路径扫描猜中。运行时变更将同一冻结风险带入 [TDD 追溯](tdd-providers.md#tddimpact-trace-v2)：权限、并发、幂等、事务、数据访问、契约、安全和敏感日志必须有相应场景与测试类型，契约风险还必须绑定外部契约影响链。路径标记只能作为风险下限：实际 changed paths 命中标记而未声明时完成门禁阻塞；未命中不构成低风险证明。语义无法确认时提高 `uncertainty` 或转为决策阻塞。

```json
{"schema_version":2,"assessment_phase":"frozen","scope":"local","coupling":"single","uncertainty":"low","verification":"local","risk_flags":[],"cross_session":false,"delegable_tasks":0,"context_isolation_benefit":false}
```

将画像通过 stdin 传给 `python3 "$CONVERGE_SKILL_DIR/scripts/task_profile.py"` 只查看分类；它不接收原始请求。全量收口由控制器明确传入 `--full-closure`，绝不能由关键词、否定词或同义表达推断。正式持久状态调用 `freeze_routing(profile, allowed_paths, request_text=<raw-request>, full_closure_required=<bool>)` 生成 Routing Receipt v3；receipt 绑定画像、请求摘要、规范化路径、route、review tier、integration requirement 和 fingerprint，恢复/完成时重算。完成门禁还会检查真实 changed paths 的 scope drift，并从 SQL、迁移、权限、安全、公共 API 等路径标记发现风险升级。

`autonomy_begin.py` 应接收控制器已冻结的同形 `--task-profile-json`；省略时按 `uncertainty=high` 保守路由，不能把未知任务假定为低风险。它拒绝直接 `--full-closure`：该诉求必须先由 `converge-plan` 冻结 Plan v6 matrix。路径和显式 `--risk-flag` 只会追加风险，绝不能降低画像声明的风险。

所有会写工作区的路径均使用轻量 writer lease。`inline` 不创建正式 state、Controller Snapshot 或 worker；只读计划与审查不获取 writer lease。

因此，一个范围局部、单步骤、验证局部的金额或 SQL 修复仍是 `inline`，但其 `review_tier=high`，必须完成对应的高风险验证和独立盲审；风险不因节省拓扑开销而被降级。业务含义、公共兼容或不可逆取舍未闭合时，`uncertainty` 必须提高或转为 `blocked_decision`，不能借 `inline` 默认决定。

## fast path

通用 fast path 已停用：`git diff --ignore-all-space` 无法证明 Markdown 等文档不存在语义变化。所有改动均进入完整画像、TDD 和复核路径；只有未来引入 formatter 专属且可验证的语义安全 contract 后才能重新开放。

代码逻辑、运行时配置、依赖升级、迁移、测试语义变化、未知验证、任一风险或范围漂移都不符合 fast path，立即按完整画像路由。fast path 不是低风险业务变更的别名，不能跳过 TDD、验收或 blind review。
