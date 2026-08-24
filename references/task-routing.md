# Task Routing Contract v2

执行拓扑与风险强度分开判断。先由控制器根据需求、调用链和真实验证方式填写任务画像，再由 `scripts/task_profile.py` 确定性选择 `inline | planned | delegated | batch`。不得按文件数或主观总分路由。

- 画像字段严格校验，布尔值不接受字符串/数字，未知风险名直接阻塞，避免拼写错误静默降级。
- 最多评估两次：需求输入后的 `provisional` 画像只给出推荐路径且固定返回 `planned`，不得派发；快速范围探查后的 `frozen` 画像才可产生最终执行路径。
- `cross_session=true` 才进入 `batch`。
- 只有存在可委托任务、上下文隔离有明确收益且任务之间不互相依赖时才进入 `delegated`。
- 跨模块、跨服务、依赖步骤、未知根因、非局部验证或风险信号至少进入 `planned`。
- 高风险只提高 review/verification 强度，不单独触发代理。
- 路由冻结后只能因新证据升级；不得反复降级、重新规划或用路由扩大授权。

风险枚举与根 Skill 的审查触发器一致：金额/支付、时间/时区、SQL/Mapper、数据库迁移、事务、并发、幂等、公共 API、安全/权限、敏感日志、跨服务、发布契约及不可逆操作。

```json
{"schema_version":2,"assessment_phase":"frozen","scope":"local","coupling":"single","uncertainty":"low","verification":"local","risk_flags":[],"cross_session":false,"delegable_tasks":0,"context_isolation_benefit":false}
```

将画像通过 stdin 传给 `python3 scripts/task_profile.py` 可查看分类；正式持久状态必须调用同模块的 `freeze_routing(profile, allowed_paths)` 生成 Routing Receipt v2。receipt 绑定完整画像、规范化 `allowed_paths`、route、review tier、integration requirement 和 fingerprint；恢复/完成时重算，调用者不得覆盖派生字段。完成门禁还会用真实 changed paths 检查 scope drift，并从 SQL、迁移、权限、安全、公共 API 等路径标记发现风险升级。

所有会写工作区的路径均使用轻量 writer lease。`inline` 不创建正式 state、Controller Snapshot 或 worker；只读计划与审查不获取 writer lease。
