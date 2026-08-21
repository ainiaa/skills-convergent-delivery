# Review Protocol v2

## Request

```json
{
  "protocol_version": 2,
  "mode": "intent | blind",
  "axis": "spec | quality | integration",
  "phase": "initial | re_review | closure",
  "task_id": "required for spec/quality; omitted for integration",
  "acceptance": ["criterion"],
  "scope": ["module-or-contract"],
  "baseline": "commit-or-explicit-unavailable",
  "source_fingerprint": "sha256",
  "design_decisions": ["intent mode only"],
  "prior_findings": ["required for re_review/closure"],
  "evidence": [{"check": "command or observation", "result": "pass | fail | unknown"}]
}
```

`blind` 请求不得包含 `design_decisions`、实现者解释或完整会话。缺少验收、范围或源码指纹时返回 blocked result，不猜测。

## Result

```json
{
  "protocol_version": 2,
  "mode": "blind",
  "axis": "quality",
  "phase": "initial",
  "source_fingerprint": "same sha256",
  "independent": true,
  "status": "reviewed | blocked",
  "axis_status": "pass | findings | blocked",
  "findings": [
    {
      "fingerprint": "flow-or-contract + violated-behavior + root-cause",
      "evidence": "location, reproduction, failing check or objective output",
      "impact": "observable effect",
      "root_cause": "cause supported by evidence",
      "scope": "current | pre-existing | out-of-scope | task-local",
      "classification": "defect | suggestion"
    }
  ],
  "blocked_reason": null
}
```

## Freshness

结果只适用于完全相同的 `source_fingerprint`。任意未包含在 finding 修复中的生产代码变化会使结果 stale。

## Closure

`closure` 输入为原 finding、修复后的源码指纹和对应验证。只判断：原问题是否不再复现、验证是否新鲜通过、修复是否越界或扩大风险面。

closure 不发现新问题。若扩大风险面，主执行者最多再请求一次新的风险 review。

## Axes and bounded re-review

`spec` 对照冻结 requirement/spec 与验收项；`quality` 只能在同任务 spec 通过后检查正确性、安全、性能和可维护性；`integration` 只能在全部任务双轴通过后检查跨任务风险。integration 中仅影响单任务的 finding 标为 `task-local`，不得影响该轴结论。每个请求只含一个 axis，各轴结果不得合并或抵消。

quality 与 integration 初审必须使用 `blind` 和全新上下文；spec 可用 `intent`，但 reviewer 只能收到冻结需求/设计，不接收实现理由。源码变化后旧结果立即 stale。

`re_review` 输入同轴原 finding、修复后新源码指纹和新鲜验证，只复核原问题与修复影响面。相同 finding 指纹重复、源码指纹未变化或无 finding 关闭时，由编排器立即 blocked。

## Protocol v1 compatibility

`protocol_version=1` 的旧 `intent`、`blind` 和 `closure` 请求继续按原字段与原 closure 语义读取；不得推断 axis，也不得把旧结果当作 v2 轴证明。
