# 执行拓扑

先确定 writer，再决定 worktree。默认一个 writer 在当前 worktree 顺序推进。

- 只读研究和审查可使用 subagent，但 subagent 不写当前仓库。
- 同仓库并发写入只允许 `planned` 路由：计划必须冻结每个 writer 的路径、独立 worktree、隔离依据、集成人和联合验证。
- 不确定共享 API、配置、依赖或测试基础设施时，视为不隔离，改为顺序执行。
- Desktop task 提供用户可见和接管；CLI runner 只在用户明确选择后台执行时使用。

并发计划在写入前必须通过：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/execution_topology.py" < topology.json
```

该校验器只核对显式拓扑，不能证明运行时没有隐藏耦合；集成人仍须执行联合验证。
