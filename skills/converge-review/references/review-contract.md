# Review Protocol v3

## Request

```json
{
  "protocol_version": 3,
  "mode": "shared | blind",
  "axis": "spec | quality | integration",
  "phase": "initial | re_review | closure",
  "task_id": "required for every axis; integration uses the plan/task key",
  "acceptance": ["criterion"],
  "allowed_scope": ["module-or-contract"],
  "baseline_commit": "full-git-object-id",
  "source_fingerprint": "sha256",
  "prior_findings": ["required for re_review/closure"]
}
```

请求字段精确校验并 canonical fingerprint；`blind` 请求的外部材料不得包含实现者解释或完整会话。缺少 task、验收、范围、完整 baseline 或源码指纹时返回 blocked result，不猜测。

## Result

```json
{
  "protocol_version": 3,
  "mode": "blind",
  "axis": "quality",
  "phase": "initial",
  "source_fingerprint": "same sha256",
  "independent": true,
  "status": "pass | findings | blocked",
  "findings": [
    {
      "fingerprint": "lowercase sha256 of the stable finding identity",
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

quality 与 integration 初审必须使用 `blind`、`independent=true` 和全新上下文；spec 可用 `shared`，但 reviewer 只能收到冻结需求/设计，不接收实现理由。编排器只有在 `reviewer_ref` 对应本轮已登记、role 为 reviewer 且宿主状态 completed 的 worker 时才接受 pass。源码变化后旧结果立即 stale。

`re_review` 输入同轴原 finding、修复后新源码指纹和新鲜验证，只复核原问题与修复影响面。相同 finding 指纹重复、源码指纹未变化或无 finding 关闭时，由编排器立即 blocked。

## Protocol v1 compatibility

`protocol_version=2` 的 `intent|blind`、`reviewed|blocked` 与描述性 finding 指纹，必须先通过下列可执行边界转换为 v3 状态记录；v3 公开结果也使用同一入口校验。adapter 会核对 result 的 axis/phase/mode/source 与冻结 request 完全一致，并输出 `task_id/request_fingerprint`：

```bash
python3 scripts/review_contract.py normalize --input - --reviewer-ref <worker-ref> \
  --request '<canonical-request-json>' < result.json
```

只允许 stdin，退出码 0 的 JSON 才能追加到 Single State Review v3 round。`protocol_version=1` 的旧请求只按原 closure 语义读取；不得推断 axis，也不得把旧结果当作 v3 轴证明。
