# Review Protocol v1

## Request

```json
{
  "protocol_version": 1,
  "mode": "intent | blind",
  "acceptance": ["criterion"],
  "scope": ["module-or-contract"],
  "baseline": "commit-or-explicit-unavailable",
  "source_fingerprint": "sha256",
  "design_decisions": ["intent mode only"],
  "evidence": [{"check": "command or observation", "result": "pass | fail | unknown"}]
}
```

`blind` 请求不得包含 `design_decisions`、实现者解释或完整会话。缺少验收、范围或源码指纹时返回 blocked result，不猜测。

## Result

```json
{
  "protocol_version": 1,
  "mode": "blind",
  "source_fingerprint": "same sha256",
  "independent": true,
  "status": "reviewed | blocked",
  "findings": [
    {
      "fingerprint": "flow-or-contract + violated-behavior + root-cause",
      "evidence": "location, reproduction, failing check or objective output",
      "impact": "observable effect",
      "root_cause": "cause supported by evidence",
      "scope": "current | pre-existing | out-of-scope",
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
