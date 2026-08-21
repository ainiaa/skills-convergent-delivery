# Review Orchestration Contract v1

控制器按风险选择复核成本。需求符合性与实现质量仍分别保存结论；普通任务由同一个 fresh reviewer 接收两个有序单轴请求，先 `spec`，通过后再 `quality`。低风险任务使用实现者自检和新鲜验证，不创建 reviewer。高风险任务使用一个 blind reviewer，同样按单轴顺序执行。只有多任务或跨服务计划才增加一次 integration review。任何源码变化都会使旧结果 stale。

```json
{
  "repair_budget": 1,
  "re_review_budget": 1,
  "on_no_progress": {"status": "blocked"},
  "on_repeated_finding": {"status": "blocked"}
}
```

一轮 finding 按根因合并后只允许一次 repair 和一次定向 re-review；`closure` 与 `re_review` 共用唯一复核额度。修复后 `source_fingerprint 未变化`、没有原 defect 关闭、re-review 返回相同 finding 指纹，或预算耗尽仍有 defect 时立即 blocked，不再循环。

仅当计划包含多个任务或跨服务契约，并且全部任务结论均为新鲜 pass 后，发起一次 integration 初审。integration 只审查跨任务风险：接口组合、数据映射、共享状态、迁移/执行顺序和端到端路径；task-local finding 不计入 integration 结论。integration 有跨任务 defect 时使用同一固定 repair/re-review 预算，但不得重新开启 initial review。

旧 Protocol v1 的 intent、blind 与 closure 请求保持可读，但不自动映射到新轴，也不能据此跳过 v2 门禁。
