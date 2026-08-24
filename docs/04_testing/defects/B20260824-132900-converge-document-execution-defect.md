# 缺陷记录：Converge 文档执行契约闭环

作者：Jeff.Liu

## 根因

- Plan v5 的 `decisions` 只校验为列表，未决公共契约可以伪装成普通记录并进入执行。
- `plan_check.py audit` 即使返回 `complete=false` 也退出 0，完成门禁依赖模型阅读 JSON。
- Controller Snapshot 冻结 Eval helper 却不允许 trusted runner 执行；Eval 又从 candidate 路径读取 judge/catalog，候选可修改自己的裁判。
- Eval worker registry 是调用方直接填写的列表，缺少来源文件；`touched_paths` 未拒绝绝对路径和 `..`；文档声明 commit/tree，但 helper 只接受 commit。
- selector 运行错误与正常未选择共用 `<none>`，正例正确时 F1 仍可能为 1。
- 历史 defect 文档没有全部进入 evaluation catalog，按受影响面全选无法覆盖已记录逃逸。

## 修复

- Plan v5 decisions 使用字段精确的 resolved 记录；最终审计增加 `--require-complete` 非零退出门禁。旧 v1-v4 字符串 decisions 仅保留读取兼容。
- Controller Protocol v10 精确授权冻结 Eval helper；judge、catalog 与 evaluator 固定到执行 helper 的旧 Snapshot，并输出各自 fingerprint。
- 样本绑定默认 managed state root 中的正式 Single State v10，由冻结 `delivery_next.py` 完整校验 workspace、Controller Snapshot、evaluator role 与 host-observed 终态 tree receipt，不建立第二套 registry；Git source 支持 commit/tree；样本路径拒绝绝对路径、`..` 和反斜杠。v9→v10 首次授权 Eval helper 的 locked differential 明确记为 uncovered，不由 candidate runner 自行放行。
- selector 错误单列 `<error>` 和 `error_count`，存在运行错误时 F1 不得保持满分。
- catalog 增加既有遗漏 defect 与本轮逃逸场景，并由测试要求每份 defect 文档至少贡献一个历史场景。

## 行为测试

- `test_only_resolved_structured_decisions_can_enter_execution`
- `test_audit_reports_partial_missing_changed_and_scope_drift`
- `test_trusted_runner_executes_only_the_frozen_batch_helpers`
- `test_sources_may_be_frozen_git_trees`
- `test_judge_worker_and_touched_paths_are_bound_to_frozen_inputs`
- `test_touched_paths_cannot_escape_even_when_repository_root_is_allowed`
- `test_selector_errors_are_not_reported_as_no_selection_or_perfect_f1`
- `test_every_defect_document_contributes_a_historical_scenario`

## 范围

本轮不启用自进化运行时，不新增依赖、后台 hook、memory bank 或外部副作用。自进化参考只保存于 `docs/02_design/architecture/self-improving.md`。
