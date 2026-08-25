---
name: converge-eval
description: Evaluate Converge Suite behavior with frozen control/candidate comparisons, fresh multi-sample decisions, and regressions selected from touched control surfaces. Use after changing Converge rules; do not use for implementation, review, or deployment.
metadata:
  compatibility: Requires Git and Python 3.9+; install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge Eval：独立行为验收

只负责有限、可复现的行为评估。不得实现候选规则、修改被测工作区、替代 `converge-review` 做代码审查，或直接执行外部副作用。

## 输入与冻结

开始前读取 [机器契约](references/evaluation-contract.json)。修改 Converge 自身时，必须在接触 candidate 前创建 Controller Snapshot；本轮 catalog、judge 和 evaluator 只能来自该旧快照，不能从 candidate 读取。control/candidate 必须是被测 Git 仓库可解析、tree 不同的完整 commit 或 tree。`worker_state_source` 必须是 `delivery_state.py` 在默认 managed state root 推导的正式 Single State v10 路径，位于候选仓库外，并绑定当前 `--repository` workspace 与正在执行的旧 Snapshot；其中样本 worker 均为 completed evaluator，且 tree receipt 为 host-observed、无 active/unexpected refs。不得自由填写平行 worker registry。每个样本的 `touched_paths` 必须是 `allowed_scope` 内不含绝对路径、反斜杠或 `..` 的仓库相对路径。Sample v4 的 `evidence_source` 必须是候选仓库外的绝对 JSON artifact，使用 `evaluator_attested` 明确其来源级别，并绑定 worker、judge 与双侧结果；它不能冒充宿主直接签名的结果。旧 `samples=["pass"]` 或 Sample v3 不是证据，必须拒绝。

通过 live trusted runner 执行冻结 helper，不能直接运行 candidate 中的副本：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/controller_snapshot.py" run \
  --descriptor <old-snapshot-or-state-json> \
  --script skills/converge-eval/scripts/eval_contract.py -- \
  --input <evaluation-request.json> --repository <absolute-candidate-repository>
```

request 中的 `judge_source` 必须精确指向 `<old-snapshot-root>/skills/converge-eval/references/evaluation-contract.json`；helper 从自己的旧快照读取 `references/evaluation-catalog.json`，用同一快照的 `delivery_next.py` 完整校验 Single State，并在结果中输出 judge、catalog、evaluator、state-validator 与 worker-state fingerprint。缺少旧快照或正式 worker state 时必须阻塞。

control 与 candidate 必须运行相同场景、输入、判定器和样本预算；分别保存原始结果，再计算差分。不能冻结旧版时不得用当前候选冒充对照。

仅 Controller Protocol v9→v10 首次把 Eval helper 加入 trusted runner 时，旧 v9 Snapshot 虽含 helper 但确定性拒绝执行。该次迁移必须保存旧 runner 的 unauthorized 证据、一个 fresh 独立只读 evaluator 报告和全量/定向测试，并把 locked differential 明确列为 `uncovered`；不得宣称 locked eval 通过。此 bootstrap 不适用于 v10 之后的任何变更。

## 场景集合

1. `known_acceptance`：由冻结验收项直接生成的场景。
2. `history`：选择 catalog 中 `control_surfaces` 与本次 `touched_control_surfaces` 有交集的全部条目，不得人工漏选。
3. `exploration`：针对仍有不确定性的受影响边界做少量新探针，不把探索通过写成完整证明。
4. `uncovered`：没有可执行场景、缺少能力或证据、以及 catalog 未覆盖的受影响面。

四类结果分别报告，不合并、不互相抵消。历史条目无匹配不等于历史风险为零；应明确 catalog 覆盖范围。

## 多样本与判定

确定性场景默认一个 fresh-context sample；只有修改路由、循环、worker 清场等关键模型决策，或首次结果不稳定时，才使用契约规定的三个 fresh workers。关键决策必须对每个 required known acceptance 和已选 history scenario 分别获得三个不同 `worker_ref`；无关 exploration 不能用来凑数。每个 Sample Receipt 必须绑定 scenario/class、control/candidate 来源、同一 judge 指纹、worker ref、原始 evidence source 与双侧结果，并由 canonical receipt 指纹防止篡改。报告样本数、通过数、失败数、通过率与二元结果方差；单次 PASS 只能证明该次样本通过，不能证明稳定。

candidate 只有在已知验收不回归、历史逃逸不复现，且差分证据未显示稳定性下降时才可通过。exploration 单独统计且不阻断 gating 完成；失败仍必须原样报告，不能改写成已知回归。未覆盖范围始终保留。Skill 触发/角色隔离另用冻结快照中的 `scripts/trigger_eval.py` 实际调用 selector 并报告 confusion matrix 与 F1；`test_trigger_evals.py` 的数据形状检查不能替代该运行。

## 有限修订

每轮只允许根据新行为证据修订 candidate 规则一次，然后用同一场景集合和新的 fresh samples 复验。最多三次规则修订；任意连续一次修订没有改善预先冻结的失败数或稳定性指标，立即停止并升级，保留 control/candidate 原始证据。不得递归规划、启动无界自我改写或以更换判定器制造改善。

## 副作用边界

允许只读检查和隔离临时工作区中的可丢弃运行。不得直接执行外部副作用，包括发送消息、发布、部署、安装、push、tag、真实审批或生产写入；只报告需要另行授权的动作。清理本次临时资源后输出机器契约规定的四类结果与停止原因。
