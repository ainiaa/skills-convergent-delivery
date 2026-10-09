# 局部阻塞与独立事项推进

需求由本会话用户确认：一项卡住不结束整个已授权任务，继续不依赖该项且有独立验证的事项；无可推进项再聚合报告阻塞，不把未覆盖证据写成完成。

复用 Plan v6 的 `depends_on`、`owned_paths`、`verification` 及既有任务结果；下一动作共用 `plan_execution.py`。普通同会话计划不新建运行台账，受管多任务只扩展既有 Batch state。单任务子 run 的 block、租约、清场和验收门禁保持有效，父控制器在确认子 run 停止且源码边界安全后选择其他任务。

局部阻塞只接受已确认的验收工具缺失/超时：冻结原因、证据和阻塞任务。业务/权限/安全决定、真实验证失败、未知错误、失联 runner、清场不明、用户停止以及预算耗尽属于全局阻塞。共享路径或依赖关系将阻塞传播到相关任务；范围重叠检查不受任务排列先后影响，排在阻塞项之前的待执行项也等待。无关任务按冻结顺序依次推进。依赖只由有证据的完成结果满足，tooling uncovered 不能当作成功。

阻塞事项不自动重试。同一工具在当前源码边界产生新的 observed pass 回执后，可由控制器沿现有有限恢复流程开启该事项一次新的尝试，保留旧记录与已消费预算，不重放不确定派发。普通计划复用已有 autonomy action attempts，在执行恢复前持久化动作意图；已执行恢复的结果或历史缺失时停止。尚未满足全计划验收时最多报告局部交付；不得因剩余事项都已阻塞生成 complete。

受管状态兼容旧 v4 顺序模式；新 v5 冻结依赖和局部阻塞。局部阻塞写入走既有 revision/CAS writer，只改变一个 batch。依赖和已记录阻塞不可被后续候选悄悄修改；当前任务从状态派生，阻塞清单从状态派生，不建立第二份可写进度。恢复读取同一状态，不重新选择已完成或已阻塞事项。

历史验收沿实际源码/checkpoint 链检查依赖顺序，不能仅凭最终完成集合放行；无改动回执插入满足依赖的源码边界位置，修改后回退也保留完整链。当前最终验收出现真实失败时，普通计划和 Batch 均停止推进。

重复源码边界存在多种轨迹时，依赖顺序重建最多检查 `max(64, 8 × 有边界尝试数)` 个状态；无法证明合法顺序时保持阻塞。工具超时/缺失回执继续标记未覆盖，不当作真实测试失败。受管历史的委托清场在状态导入和每次恢复读取时重新核对；普通已执行动作丢失结果时停止，不将其重新解释为待执行项。

所有独立实现已完成而最终验收工具仍未恢复时，聚合返回 tooling uncovered 的阻塞结果；不再次采样相同验收，也不标记整个任务完成。独立实现引起的源码变化只会使旧验收回执过期，不会解除其中记录的工具故障；仍需同一工具在当前源码上的新真实通过证据才能消除该缺口。普通计划先把故障回执写入已有 Single State 的 `ledger.acceptance`，更新时由既有 `acceptance_history` 留存；后续输入即使清空最终验收，也不能擦除历史阻塞。Batch v5 只有所有 Batch 已完成时才可记录最终验收 pass，导入与状态更新共用该门禁，避免提前冻结会随实现变旧的证据。故障验收项不能改回 unknown 占位或新的失败回执，只能由同工具的当前 pass 解除，已通过项继续不可改写。

恢复的旧失败即使未携带修改边界，也要按工具回执的实际源码位置入链，并先于恢复尝试；不能把它默认放到基线之前。Batch 完成还必须要求当前 HEAD 等于完整验证链的末端，不能退回较早的已完成提交后放行。恢复只能为调度器当前选中的事项消费预算；若独立事项排在它之前，先完成独立事项，再取得当前检查点的恢复证据，避免不可改写的恢复回执被其他提交提前失效。

单任务和全局 block 不恢复业务执行。仅在阻塞原因精确为最终验收工具缺口、所有实现已完成、冻结验收均有当前源码的真实通过证据且每个旧工具缺口均由同 argv 通过证据解除时，允许 blocked 直接进入正常 complete 校验；普通计划还要求 environment 分类和源码不变。仍须经过已有完成、清场、历史归档、预算和状态更新门禁，不恢复 active、不清零预算，不重放业务动作。不引入新的后台调度器：宿主控制器仍只执行一个下一动作，普通单任务不增加状态、文件或代理。

## 参考与行为验证

2026-10-09 闭环修复沿用下表已核对的历史状态与新鲜证据机制，不新增协议或台账：历史 blocked delegate 的源码绑定真实清洁 checkpoint，后续独立提交不改写旧回执；当前工作区仍须符合既有执行边界。Plan 与 Batch 的真实失败证据在同命令当前 pass 出现前不能擦除，源码变化不能解除。未完成实现期间该恢复 proof 保持最终验收 unknown，避免提前冻结 final pass。对应实际 Git/CAS 回归：`test_blocked_delegate_history_survives_independent_source_changing_completion`、`test_historical_local_block_rejects_unverified_or_dirty_source_boundaries`、`test_actual_final_failure_cannot_be_erased_without_current_same_command_pass`、`test_source_changes_do_not_clear_an_unresolved_actual_final_failure`、`test_ordinary_plan_source_changes_do_not_erase_recorded_actual_failure`。不采用新的历史台账或后台恢复器：原阻塞尝试、checkpoint 链与现有验收槽已足以完成本轮校验。

先检查 Skills.sh 的 testing、planning-with-files 和连续循环条目，再核对原始源。

恢复还须核对验收项外层 freshness、结果及提供的 source_fingerprint，不能用内层当前 pass 包装明确过期或源码不一致的外层记录。最终工具阻塞直接进入 complete 的共享 helper 也检查 acceptance_history 内真实失败的同命令通过证据，不能只解除当前工具缺口。回归：`test_ordinary_plan_source_changes_do_not_erase_recorded_actual_failure`、`test_final_tool_completion_must_also_resolve_archived_actual_failures` 与原生状态直接完成的拒绝场景。

| 能力/来源 | 采用 | 不采用/原因 | 对应行为测试 |
| --- | --- | --- | --- |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 观测与控制决定分开，一次选择下一增量 | 不增加定时工作流或 actuator 角色，本仓已有控制器 | 工具缺口继续独立项，真实失败全局停止 |
| [Superpowers writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md) | 以可独立验收结果切片，明确依赖 | 不强制每步提交或创建代理，用户只授权同会话顺序实现 | 依赖/共享范围阻塞传播，无依赖任务按冻结顺序推进 |
| [planning-with-files](https://github.com/othmanadi/planning-with-files/blob/master/skills/planning-with-files/SKILL.md) | 唯一计划归属、记录错误、失败后不重复同一动作 | 不引入三份 Markdown 真源，复用既有机器状态 | 序列化恢复不重做、不清空阻塞历史 |
| Ralph 连续循环 | 检查有限任务与客观进展边界 | 本次没有充分读取其实现/测试，不作为关键设计依据；不引入无限重试 | 所有剩余项阻塞时单次聚合返回 block |
| [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md)、本机 skill-creator | 完成绑定新鲜证据，入口短、协议按需读取 | 不使用文案断言代替行为验收 | 未满足依赖、未覆盖验收和范围漂移不能 complete |

实现计划：`plan-local-blocking-20261008.json`。本次控制器旧快照已在仓库外创建；原有脏文件是上一轮同事项修改，保留并在最终 diff 中一起复核。发布、提交、推送、部署仍需独立授权。
