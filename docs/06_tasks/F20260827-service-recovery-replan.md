# Service Recovery Replan

旧的自治 service 计划废弃；不回滚已有工作区改动。

1. 终态：以独立 verifier 收据驱动 `complete`/`blocked`，并释放 lease；定向测试。
2. 恢复：runner、verifier 与写入失败在持久预算内 `blocked`，不重放不确定动作；定向测试。
3. 启动：仅隔离 worktree 可 arm，失败回滚 state/lease，service 可被唤起；定向测试。
4. 集成：无真实模型调用的完整回归与文档；`bash scripts/check.sh`。

每步只有通过本步测试后才进入下一步；仅第 4 步通过后交付。
