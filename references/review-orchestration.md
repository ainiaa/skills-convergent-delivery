# Review Orchestration Contract v1

Core 的普通/高风险门禁复用 `runner_lifecycle.py` 的单个本地只读 reviewer（Codex CLI 或 Claude Code）：冻结 profile、完整 Review v3 request，并显式提供 `--allow-execute`。该路径不要求启用多模型扩展，也不授予写入、shell 或扇出权限。其他角色、并发扇出和 OpenAI-compatible API runner 仍要求冻结 `multimodel` 扩展；无可用 CLI 或无执行授权时明确交接，不伪造独立审查回执。

控制器按风险选择复核成本。需求符合性与实现质量仍分别保存结论；普通任务由同一个有冻结 profile、request binding 与 completed role result 的外部只读 fresh reviewer 接收两个有序单轴请求，先 `spec`，通过后再独立盲审 `quality`；它只是外部证据身份，不能伪称宿主 worker。低风险任务使用实现者自检和新鲜验证，不创建 reviewer。高风险任务使用一个 blind reviewer，同样按单轴顺序执行。只有多任务或跨服务计划才增加一次 integration review。任何源码变化都会使旧结果 stale。

```json
{
  "repair_budget": 1,
  "re_review_budget": 1,
  "on_no_progress": {"status": "blocked"},
  "on_repeated_finding": {"status": "blocked"}
}
```

一轮 finding 按根因合并后只允许一次 repair 和一次定向 re-review；普通 `closure` 与 `re_review` 共用唯一复核额度。修复后 `source_fingerprint 未变化`、没有原 defect 关闭、相同 finding 指纹重复或预算耗尽仍有 defect 时立即将本 run 置为 blocked，不在本 run 循环；新根因是否能开启下一轮按下段判断。全量收口在最终验证后额外使用 `closure`：首次是初审，不消费 re-review 额度；有 finding 时，修复后的最终 closure 才消费该唯一额度。第三次请求禁止，最终仍有 finding 或 blocked 时保存 `blocked/uncovered`，不能因无法通过而丢失终态。若此前已消费修复或复核预算，保持耗尽，不重置预算。

首次交付的 review 是完成门禁，不是交付后的可选咨询。当前源码若有确认的同范围 finding，控制器在本 task 内使用尚可用的 repair/re-review 动作；未关闭时只能停止为 `blocked/uncovered`，不能以 `complete` 或“已完成、请再说继续修复”收尾。预算限制一次 managed run，不是把剩余 Bug 转交给用户的许可。

上述预算只限制当前 managed run，不撤销同会话同事项的写入授权。若最终复核发现有新证据的新的不同根因、且仍在冻结范围内，先将旧 run 以 `blocked/uncovered` 收口并保留回执；控制器核对旧 finding、源码变化和当前证据后，可按原授权在同一 task 中启动新的有限修复轮次，完成后才给用户最终结论。不得在同一 run 回填预算，也不得仅换 finding 指纹或重启任务来掩盖相同根因。相同根因、无源码或证据进展、范围外决定未获授权，或状态/lease 无法合法恢复时，停止并如实报告阻塞。

仅当计划包含多个任务或跨服务契约，并且全部任务结论均为新鲜 pass 后，发起一次 integration 初审。integration 只审查跨任务风险：接口组合、数据映射、共享状态、迁移/执行顺序和端到端路径；task-local finding 不计入 integration 结论。integration 有跨任务 defect 时使用同一固定 repair/re-review 预算，但不得重新开启 initial review。

只接受 Protocol v3。旧 Protocol v1/v2 不转换、不用于推进状态；历史记录可供人工理解，但不能据此跳过 v3 门禁。

## 本轮机制取舍

| 参考 | 采用 | 不采用及原因 | 对应行为测试 |
|---|---|---|---|
| 本机 `skill-creator`、[Superpowers writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) | 先让已知问题穿过完成门禁，再补失败回归和单轮交互场景 | 不增设另一套可写问题台账；现有 `handoff.open_issues` 已是待处理真源 | `test_complete_rejects_known_open_issues_even_when_acceptance_passes`、`authorized-delivery-closes-review-findings` |
| [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | 最终声明绑定当前源码的通过证据，且已记录问题不能被 `attention` 包装为完成 | 不承诺未知 Bug 为零；测试与审查只能证明其覆盖的范围 | `test_complete_with_known_open_issues_cannot_render_as_attention` |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md)、本机 PDLC `loop-next` | 复用现有状态、单步决定和 `blocked` 停止条件 | 不引入定时控制器、额外 Hook 状态或无限修复循环；普通开发是一次已授权任务，不是持续巡检 | `test_structured_open_issues_preserve_the_exact_item_count`、现有 review 预算回归 |
