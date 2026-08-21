# Task Routing Contract v1

执行拓扑与风险强度分开判断。先由控制器根据需求、调用链和真实验证方式填写任务画像，再由 `scripts/task_profile.py` 确定性选择 `inline | planned | delegated | batch`。不得按文件数或主观总分路由。

- 最多评估两次：需求输入后的 provisional 画像，以及快速范围探查后的 frozen 画像。
- `cross_session=true` 才进入 `batch`。
- 只有存在可委托任务且上下文隔离有明确收益时才进入 `delegated`。
- 跨模块、跨服务、依赖步骤、未知根因、非局部验证或风险信号至少进入 `planned`。
- 高风险只提高 review/verification 强度，不单独触发代理。
- 路由冻结后只能因新证据升级；不得反复降级、重新规划或用路由扩大授权。

所有会写工作区的路径均使用轻量 writer lease。`inline` 不创建正式 state、Controller Snapshot 或 worker；只读计划与审查不获取 writer lease。
