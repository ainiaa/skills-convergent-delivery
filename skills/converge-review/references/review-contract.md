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
  "prior_findings": ["prior finding SHA-256s; required for re_review and repaired closure"]
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

普通 `closure` 输入为原 finding、修复后的源码指纹和对应验证，只判断原问题是否不再复现、验证是否新鲜通过、修复是否越界或扩大风险面。

当冻结 Routing Receipt 声明 `full_closure_required=true` 时，最终 `closure` 还必须对冻结范围、当前 diff、定向图谱影响面与验收作独立盲审，可报告新的 scoped finding。该模式最多允许“初审 → 一次修复 → 最终复核”：最终复核仍有 finding 时由控制器 `blocked/uncovered`，不得再派第三次 closure。

## Axes and bounded re-review

`spec` 对照冻结 requirement/spec 与验收项；`quality` 只能在同任务 spec 通过后检查正确性、安全、性能和可维护性；`integration` 只能在全部任务双轴通过后检查跨任务风险。integration 中仅影响单任务的 finding 标为 `task-local`，可随 `pass` 保存但不得影响该轴结论；其他 finding 必须返回 `findings`。`task-local` 的 `defect` 仍是整体交付的待修问题：控制器从当前源码最新各轴记录选择原有有限修复动作，未关闭时不得 complete；`suggestion` 不触发修复。当前源码的非空 finding 必须保留结构化记录，不能只存指纹而丢失分类。每个请求只含一个 axis，各轴结果不得合并或抵消。

quality 与 integration 初审必须使用 `blind`、`independent=true` 和全新上下文；这里的全新上下文指 reviewer 独立于实现者、未继承实现理由或完整实现会话，而不是为 spec 与 quality 各派一个 reviewer。spec 可用 `shared`，但 reviewer 只能收到冻结需求/设计，不接收实现理由；同一个 fresh reviewer 可按顺序接收 spec 和 quality 的单轴请求，quality 输入仍不得包含实现理由。编排器只接受同名 frozen external runner profile 所产出的已完成可用 role result；它是外部证据身份，绝不能伪称 host worker。源码变化后旧结果立即 stale。

`re_review` 必须输入至少一个同轴历史 finding 的 SHA-256、修复后新源码指纹和新鲜验证。历史 finding 只绑定修复起点，不缩小审查范围：复核仍检查冻结验收、当前 diff 与修复影响面，并可报告新的同范围 finding。修复后的 closure 也必须携带其关闭的历史 finding；首次 full-closure 审查是唯一例外。相同 finding 指纹重复、源码指纹未变化或无 finding 关闭时，由编排器立即 blocked；新 finding 只能进入当前任务的剩余有限修复/复核预算，不能产生 successor task。

## Canonical adapter

只接受 `protocol_version=3`；adapter 会核对 result 的 axis/phase/mode/source 与冻结 request 完全一致，并输出 `task_id/request_fingerprint`：

```bash
python3 "$CONVERGE_REVIEW_SKILL_DIR/scripts/review_contract.py" normalize --input - --reviewer-ref <worker-ref> \
  --request-file <canonical-request.json> < result.json
```

结果只允许 stdin，request 只允许文件，退出码 0 的 JSON 才能追加到 Single State Review v3 round；不得把验收、范围或 findings 放进 argv。编排器必须为该 reviewer 的 frozen runner launch 配置完整 canonical request 和相同的 `review_request_fingerprint`，并将 adapter 生成的同一内部 Review v3 record 写入完成的可用 role result；外部 lifecycle 以该 request 重算摘要，且拒绝 task、baseline、source、当前 acceptance 或 frozen allowed scope 不匹配的请求；状态 record 与 role result record 不完全相同则 pass 无效。request 的 `task_id` 至多 200 字符，acceptance 至多 32 项、allowed_scope 至多 64 项、prior_findings 至多 16 项，列表文本均至多 500 字符。旧请求和结果直接拒绝。

每个 `findings` 由 adapter 原样规范化为当前不可变 round 内的 `finding_records`：仅保存 fingerprint、evidence、impact、root_cause、scope、classification，三个说明字段各不超过 500 字符。它与 `finding_fingerprints` 顺序和身份完全一致，供定向复核、恢复和用户回执追溯；不另建可写台账，也不保存 prompt、完整对话或敏感原始产物。

## 可选事实交接与环境续接

Review v3 保留既有必填字段及旧请求指纹；可附加 `evidence`（1–16 个带全文件哈希的本地 file/artifact 引用）。它们进入 blind 请求，controller 实现理由仍隐藏。引用内容是待核实事实；工具通过只来自与当前源码绑定的 observed Evidence Receipt。

`blocked_request` 仅允许 `re_review` 且 `prior_findings=[]`、非空 evidence。它绑定最新同轴同源码、无 finding 的 blocked initial；必须有此前未交接的新 passing test receipt、原已完成审查回执和剩余复核预算。只有 environment blocked 可以显式恢复；正常 finding 复核规则不变，不能用于格式恢复、业务/权限阻塞或无进展重试。完整命令见主 Skill references/multi-model.md Protocol 23。
