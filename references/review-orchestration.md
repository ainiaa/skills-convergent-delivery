# Review Orchestration Contract v1

控制器为每个任务严格执行 `spec -> quality`。两轴结果分别保存，不得合并、覆盖或相互抵消；任一轴 blocked 时不得启动后续轴。

spec reviewer 只接收冻结需求/设计和客观证据；quality 与 integration 初审必须由全新上下文执行 `blind` 审查。任何源码变化都会使旧结果 stale。

```json
{
  "repair_budget": 1,
  "re_review_budget": 1,
  "on_no_progress": {"status": "blocked"},
  "on_repeated_finding": {"status": "blocked"}
}
```

每轴只允许一次初审、一次 repair 和一次 re-review；`closure` 与 `re_review` 共用唯一复核额度。修复后 `source_fingerprint 未变化`、没有原 defect 关闭、re-review 返回相同 finding 指纹，或预算耗尽仍有 defect 时立即 blocked，不再循环。

仅当全部任务的 spec 与 quality 均为新鲜 pass 后，发起一次 integration 初审。integration 只审查跨任务风险：接口组合、数据映射、共享状态、迁移/执行顺序和端到端路径；task-local finding 不计入 integration 结论。integration 有跨任务 defect 时使用同一固定 repair/re-review 预算，但不得重新开启 initial review。

旧 Protocol v1 的 intent、blind 与 closure 请求保持可读，但不自动映射到新轴，也不能据此跳过 v2 门禁。
