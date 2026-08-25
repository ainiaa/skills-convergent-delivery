# Task Routing Contract v2

执行拓扑与风险强度分开判断。先由控制器根据需求、调用链和真实验证方式填写任务画像，再由 `scripts/task_profile.py` 确定性选择 `inline | planned | delegated | batch`。不得按文件数或主观总分路由。

- 画像字段严格校验，布尔值不接受字符串/数字，未知风险名直接阻塞，避免拼写错误静默降级。
- 最多评估两次：需求输入后的 `provisional` 画像只给出推荐路径且固定返回 `planned`，不得派发；快速范围探查后的 `frozen` 画像才可产生最终执行路径。
- `cross_session=true` 才进入 `batch`。
- 只有存在可委托任务、上下文隔离有明确收益且任务之间不互相依赖时才进入 `delegated`。
- 跨模块、跨服务、依赖步骤、未知根因、非局部验证或多个可委托切片至少进入 `planned`。
- 高风险只提高 review/verification 强度，不单独触发代理。
- 路由冻结后只能因新证据升级；不得反复降级、重新规划或用路由扩大授权。

风险枚举与根 Skill 的审查触发器一致：金额/支付、时间/时区、SQL/Mapper、数据库迁移、事务、并发、幂等、公共 API、安全/权限、敏感日志、跨服务、发布契约及不可逆操作。

```json
{"schema_version":2,"assessment_phase":"frozen","scope":"local","coupling":"single","uncertainty":"low","verification":"local","risk_flags":[],"cross_session":false,"delegable_tasks":0,"context_isolation_benefit":false}
```

将画像通过 stdin 传给 `python3 scripts/task_profile.py` 可查看分类；正式持久状态必须调用同模块的 `freeze_routing(profile, allowed_paths)` 生成 Routing Receipt v2。receipt 绑定完整画像、规范化 `allowed_paths`、route、review tier、integration requirement 和 fingerprint；恢复/完成时重算，调用者不得覆盖派生字段。完成门禁还会用真实 changed paths 检查 scope drift，并从 SQL、迁移、权限、安全、公共 API 等路径标记发现风险升级。

所有会写工作区的路径均使用轻量 writer lease。`inline` 不创建正式 state、Controller Snapshot 或 worker；只读计划与审查不获取 writer lease。

因此，一个范围局部、单步骤、验证局部的金额或 SQL 修复仍是 `inline`，但其 `review_tier=high`，必须完成对应的高风险验证和独立盲审；风险不因节省拓扑开销而被降级。业务含义、公共兼容或不可逆取舍未闭合时，`uncertainty` 必须提高或转为 `blocked_decision`，不能借 `inline` 默认决定。

## fast path

fast path 在 task profile 之前结束：只接受已跟踪普通文档的单文件纯格式改动，必须不改变运行时行为、无业务/公共契约/权限/发布取舍、`risk_flags=[]`、范围局部，且已有可实际执行的确定性检查。先获取 writer lease，再调用 `fast_path.py --workspace <path> --baseline <commit> --risk-flags '[]' --lease-root <root> --repo <absolute-git-common-dir> --task-key <key> --run-id <run> --writer-id <writer> -- <check argv>`：它要求当前 run 同时拥有未过期的 workspace/task lease，check 前后 Source Receipt 完全一致、检查实际成功并绑定当前 Source Receipt，且 `git diff --ignore-all-space` 对唯一文档路径为空；`SKILL.md`、未跟踪文档、风险路径、运行时路径、多文件、语义内容、会修改源码的 check、无回执或无有效 lease 一律拒绝。不创建 Provider Binding、task profile、state、snapshot 或 worker。

代码逻辑、运行时配置、依赖升级、迁移、测试语义变化、未知验证、任一风险或范围漂移都不符合 fast path，立即按完整画像路由。fast path 不是低风险业务变更的别名，不能跳过 TDD、验收或 blind review。
