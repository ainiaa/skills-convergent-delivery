---
name: converge-eval
description: Evaluate Converge Suite behavior with frozen control/candidate comparisons, fresh multi-sample decisions, and regressions selected from touched control surfaces. Use after changing Converge rules; do not use for implementation, review, or deployment.
metadata:
  compatibility: Requires Git and Python 3.11+; install the complete Converge Suite. Supports Codex and Claude Code.
---

# Converge Eval：独立行为验收

只负责有限、可复现的行为评估。不得实现候选规则、修改被测工作区、替代 `converge-review` 做代码审查，或直接执行外部副作用。

## 当前能力预检

确定性规则和脚本回归优先使用下一节的 `--preflight --deterministic`。只有模型行为评估才使用默认模式，开始收集模型样本前运行 `python3 "$CONVERGE_EVAL_SKILL_DIR/scripts/eval_contract.py" --preflight`；本目录变量按下一节解析。默认模型评测模式没有 concrete evaluator lifecycle bridge，该模式的公共 API 与 CLI 返回 `status=uncovered`、`eligible=false`、`stop_reason=unavailable_host_bridge`，CLI 退出码为 2，且不读取样本工件。不得要求用户构造不可生成的 worker registry，不能把 blocked legacy fixture 或离线统计测试当作正式 Eval 通过。

此时停止模型 Eval，保留模型行为 locked differential 为 `uncovered`；已授权的本地实现、修复与回归测试可继续，但它们不能替代正式验收或发布门禁。以下是冻结的目标证据契约及离线统计规则，只有以后落地真实 bridge 并通过入口行为测试，才可启用采样。私有 `_evaluate_receipts` 仅用于离线 bookkeeping，输出 `evidence_level=diagnostic`、`release_status=uncovered`，不是替代入口。修改判定器时继续保留旧快照，不能用本次候选自证通过。

## 确定性进程 bridge

`--preflight --deterministic` 探测本地进程模式；此模式运行真实 unittest 判定器，不调用模型、不创建 worker。必须从仓库外的 Controller Snapshot 启动，复用上述 trusted runner，并在 Eval 参数中加入 `--deterministic`。请求文件包含：

```json
{
  "controller_snapshot": {"...": "完整旧版 Snapshot descriptor"},
  "control_source": "<完整 Git commit 或 tree>",
  "candidate_source": "<不同的完整 Git commit 或 tree>",
  "suite": "evals/local-suite.json",
  "timeout_seconds": 600
}
```

`suite` 只从 control tree 读取，须在候选修改前冻结；它包含 `allowed_scope`、`touched_control_surfaces` 和 `scenarios`。每个场景为 `{"id":"唯一验收或历史 ID","class":"known_acceptance|history|exploration","judge":"evals/test_case.py"}`。判定器使用独立、非空的标准库 unittest 文件，通过 cwd 或导入目标模块测试被测行为；判定逻辑不得从 candidate 的测试辅助文件动态加载。至少一个 known acceptance，且包含旧 catalog 中全部匹配 history ID。

场景和判定器都来自 control；候选不得修改它们或超出 allowed_scope。helper 为每个场景的每一侧重新导出 Git tree，单独运行冻结判定器，退出后确认进程组清场并删除临时目录；仅支持指向临时工作区内部的相对符号链接。最多 32 个场景，总预算最多 600 秒；零测试、跳过、预期失败、错误、超时归为 uncovered；对照侧缺证据不能计为修复。exploration 单列且不抵消 gating 失败。不接受外部手填的结果样本。

结果为 `deterministic-eval-v1`、`evidence_level=process_observed`，包含双侧退出码、测试分类、输出摘要、tree、suite、catalog 和 controller 指纹及四类结果；`release_status=uncovered` 保留模型行为和宿主 lifecycle 边界。临时目录与进程组是测试隔离，不是针对恶意代码的 OS sandbox；只运行已授权的本地测试。

首次加入该 bridge 时，旧快照没有此入口，不能用新候选自证旧版 locked Eval 通过。该次实现以真实 bridge 集成回归验证；后续任务可以冻结已含 bridge 的旧版本后使用。默认模型模式和既有 v5 离线统计契约保持不变，以下 worker/multi-sample 规则仅适用于模型模式。

## 输入与冻结

先将本 `SKILL.md` 所在目录的绝对路径记为 `CONVERGE_EVAL_SKILL_DIR`；Suite helper 从其上两级目录解析，不能依赖被测仓库的 `scripts/`。

开始前读取 [机器契约](references/evaluation-contract.json)。修改 Converge 自身时，必须在接触 candidate 前创建 Controller Snapshot；本轮 catalog、judge 和 evaluator 只能来自该旧快照，不能从 candidate 读取。control/candidate 必须是被测 Git 仓库可解析、tree 不同的完整 commit 或 tree。`worker_state_source` 必须是 `delivery_state.py` 在默认 managed state root 推导的正式 Single State v10 路径，位于候选仓库外，并绑定当前 `--repository` workspace 与正在执行的旧 Snapshot；其中样本 worker 均为 completed evaluator，且 tree receipt 为 host-observed、无 active/unexpected refs。不得自由填写平行 worker registry。每个样本的 `touched_paths` 必须是 `allowed_scope` 内不含绝对路径、反斜杠或 `..` 的仓库相对路径。Sample v4 的 `evidence_source` 必须是候选仓库外的绝对 JSON artifact，使用 `evaluator_attested` 明确其来源级别，并绑定 worker、judge 与双侧结果；它不能冒充宿主直接签名的结果。旧 `samples=["pass"]` 或 Sample v3 不是证据，必须拒绝。

通过 live trusted runner 执行冻结 helper，不能直接运行 candidate 中的副本：

```bash
python3 "$CONVERGE_EVAL_SKILL_DIR/../../scripts/controller_snapshot.py" run \
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

修改 Schema v11 自治交付时，另运行冻结的 `references/autonomous-delivery-evaluation.json`：它至少覆盖 15 条从 active 到 complete、blocked 或 decision 的轨迹，且只保留状态、耗时、用量、verdict 与 receipt 摘要。普通评测不得保存 prompt/transcript 或调用真实模型；真实宿主 smoke 只可在用户明确选择后单独执行，不能拿预检或模型自述代替。

## 多样本与判定

确定性场景默认一个 fresh-context sample；只有修改路由、循环、worker 清场等关键模型决策，或首次结果不稳定时，才使用契约规定的三个 fresh workers。关键决策必须对每个 required known acceptance 和已选 history scenario 分别获得三个不同 `worker_ref`；无关 exploration 不能用来凑数。每个 Sample Receipt 必须绑定 scenario/class、control/candidate 来源、同一 judge 指纹、worker ref、原始 evidence source 与双侧结果，并由 canonical receipt 指纹防止篡改。报告样本数、通过数、失败数、通过率与二元结果方差；单次 PASS 只能证明该次样本通过，不能证明稳定。

candidate 只有在已知验收不回归、历史逃逸不复现，且差分证据未显示稳定性下降时才可通过。exploration 单独统计且不阻断 gating 完成；失败仍必须原样报告，不能改写成已知回归。未覆盖范围始终保留。Skill 触发/角色隔离另用冻结快照中的 `scripts/trigger_eval.py` 实际调用 selector 并报告 confusion matrix 与 F1；它的本地结果不能作为 release，`--release` 在真实宿主 bridge 缺席时必须为 `uncovered`；`test_trigger_evals.py` 的数据形状检查不能替代该运行。

## 有限修订

每轮只允许根据新行为证据修订 candidate 规则一次，然后用同一场景集合和新的 fresh samples 复验。最多三次规则修订；任意连续一次修订没有改善预先冻结的失败数或稳定性指标，立即停止并升级，保留 control/candidate 原始证据。不得递归规划、启动无界自我改写或以更换判定器制造改善。

## 副作用边界

允许只读检查和隔离临时工作区中的可丢弃运行。不得直接执行外部副作用，包括发送消息、发布、部署、安装、push、tag、真实审批或生产写入；只报告需要另行授权的动作。清理本次临时资源后输出机器契约规定的四类结果与停止原因。
