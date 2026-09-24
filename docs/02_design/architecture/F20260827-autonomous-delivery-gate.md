# Autonomous Delivery Gate

## 目标

在用户一次明确授权“闭环执行”后，控制器在冻结范围内持续推进；用户不是 scheduler。终态只有三种：有当前证据的 `complete`、可恢复且有原因的 `blocked`，或需要用户授权的决策边界。

这不是后台 agent、swarm 或 Agent 聊天记录恢复机制。默认仍是普通 Converge 路径；自治只对显式 Schema v11 run 生效。

## 单一真源与路径

```text
用户明确授权
  → Single State v11: 冻结 manifest、预算、当前源码/证据
  → autonomy_gate.py: 只读裁决一个下一 Runtime Action
  → 控制器执行一个动作并写入状态/收据
  → active: 继续；complete|blocked: delivery_report.py 生成回执
```

`autonomy` 只存在于既有 Single State 的 `execution_control` 内。它没有第二 ledger：manifest、范围审计批次、源指纹、审计覆盖和有限预算均由同一状态验证。模型的 “done” 文本不能经过 gate。

初始全范围审计若发现问题，状态确定性进入 `autonomy-repair`，只允许一次修复和一次新的全范围复审。复审必须使用新的源码指纹；重复 finding、陈旧证据、范围/风险漂移、无效状态或预算耗尽都必须终止为 `blocked`。每次宿主 Stop Hook 只交付一个经过 `run_contract.py` 验证的 action，避免用长 prompt 重新规划整个任务。

完成还必须有至少一个已 `committed` 的 action；空 action 历史不能完成。每个 audit batch 保存产生它的 Evidence Receipt 指纹，完成门禁要求同一回执对当前 Source Receipt 成功；service 额外要求该回执的 argv 与冻结 `audit_argv` 完全相同。Gate 在非终态没有 lease root 时只返回阻断原因，不返回可执行 action。

## 宿主边界

Stop Hook 是显式、可撤销的 adapter，而非默认安装项。Codex 安装时同时注册 `UserPromptSubmit`：明确快捷指令“继续修复”/“继续修复已知问题”/`continue repair` 创建当前 workspace 的受限 repair gate；随后 Codex Desktop 与 CLI 以原生 `decision:block` 在原 task 中交付冻结的下一动作。新建 Hook run 必须保存宿主 `session_id`，身份缺失时不创建门禁；Stop 仅能接续匹配的会话，身份缺失时阻断而非跨会话接管。`session_id` 只隔离活动 run，不单独证明用户仍在谈同一事项，也不承诺宿主恢复时 ID 恒定。完成状态不被改写；同会话再次询问问题时，Hook 只提供唯一历史事项的范围线索，由当前控制器核对事项指代后决定是否启动新的有限修复轮次。新会话只读询问不借用旧写入授权，明确修复请求本身即新授权。Hook 先写入一次性 intent；带 `stop_hook_active` 的下一 Stop 若未观察到提交，则终止为 `blocked/no_progress` 并释放 lease，返回一次 block 以要求报告阻塞。Claude Code 2.1.246+ 同样直接返回 `decision:block`。`--autonomy` 先运行本机 preflight，预检失败拒绝注册；不得从 Hook 另起 `--resume` 进程，因为宿主拒绝同时写入同一 transcript。普通验证仅在临时 HOME 测试配置合并、适配器输入输出与原生 block 决策；它不安装真实全局 Hook、不调用模型，也不宣称验证了宿主真实回调。目标宿主中的 live smoke 必须由用户另行选择。

Codex/Claude Stop continuation 不承诺后台、跨会话或掉线后的自主恢复。需要该能力时，用户可显式启用 macOS `autonomy-service`：它使用 state 中冻结的外部 CLI runner 和 verifier argv，在独立隔离 worktree 中逐动作执行。每个动作先落盘 intent/running，模型回执仅形成 observed，独立 verifier 成功后才 committed；重启发现 running 则按未知结果 block，绝不盲目重放。service 只有用户显式冻结 `audit_findings_exit_code` 时才把该 audit exit 解释为可修复 finding，其他非零仍为阻塞。重启扫描会幂等清理已写终态但未释放的 lease；永久无效 state 只输出一次诊断并成功退出，避免 LaunchAgent 重启循环。service 与 Hook continuation 互斥。多个 active run 或状态损坏必须保持有证据的 blocked/handoff，而不是创建新会话。

## 交付、暂停与恢复

- 启用：用户明确闭环执行；如需 Stop Hook，再显式安装 `--autonomy`。
- 暂停：用户停止、权限/不可逆动作或宿主能力不足，状态记录为 `blocked`/decision 与 `handoff`。
- 恢复：同一 run 使用 writer lease、revision、冻结 manifest 和最新证据继续；旧 Schema v10 不会被静默升级为 v11。
- 卸载：`--autonomy-uninstall` 只移除本 Skill 精确注册的 Hook command，保留状态与其他 Hook。
- 结束：`delivery_report.py` 只从已验证状态、当前范围 audit 和 Evidence Receipt 生成报告；审计摘要不保存模型 transcript。

## 验收

固定 15 条以上的无 transcript 轨迹目录覆盖：完整修复、新 finding、重复失败、陈旧证据、范围/风险漂移、决策/权限门禁、用户停止、宿主不支持、多 run 与恢复交接。完整套件不执行真实模型、Hook 安装或外发操作。

## 跨目录兼容取舍（2026-09-23）

| 参考机制 | 采用 / 不采用与原因 | 对应行为测试 |
|---|---|---|
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md)、Superpowers writing-skills | 采用真实失败先行；不增加文案关键词断言或新评估器 | 旧快照子目录 Stop、根目录与子目录重复租约先红后绿 |
| [OpenAI Hooks](https://learn.chatgpt.com/docs/hooks)、planning-with-files、HumanLayer 控制面 | 采用宿主 `session_id` 隔离活动 run，并用既有终态作同会话只读复查线索；不采用仅凭会话/工作区自动认定同一事项、复制授权到新会话或新增事项注册表。缺失身份时不创建新 Hook 门禁，恢复后 ID 是否稳定及信任/回调仍须真实宿主验证 | `test_explicit_shortcut_without_host_session_id_does_not_arm`、`test_session_bound_run_does_not_continue_in_another_conversation`、`test_same_conversation_recheck_offers_only_advisory_context`、`test_recheck_does_not_select_an_old_completion_when_another_task_is_active` |
| [planning-with-files](https://github.com/othmanadi/planning-with-files/blob/master/skills/planning-with-files/SKILL.md)、HumanLayer design-control-loop | 采用恢复时核对既有状态与单写者边界；不新增恢复状态文件或后台控制器 | `test_root_prompt_reuses_a_pre_upgrade_subdirectory_run`、`test_root_acquire_respects_a_pre_upgrade_subdirectory_lease` |
| 宿主 Stop Hook 的冻结快照边界 | 采用当前入口把 `cwd` 规范为活动 run 的 workspace，再执行旧快照；不改写冻结控制器 | `test_frozen_hook_receives_the_active_run_workspace_from_a_subdirectory`；真实宿主回调仍未覆盖 |
| [Git worktree 管理目录](https://git-scm.com/docs/gitrepository-layout)、[Git 环境变量](https://git-scm.com/docs/git)、HumanLayer 控制面与宿主 Stop Hook | 采用“先检查当前工作树是否存在活动状态，再做 Git 身份查询”；无状态或仅终态历史时放行，活动状态或无法确认 Git 布局时阻断。`.git` 即使是悬空符号链接也算存在但布局不可确认；显式设置 `GIT_DIR` 时优先采用该 Git 身份（即使祖先有另一个 `.git`），查询 Git 的真实 worktree/common-dir，再检查受管状态，查询失败则阻断。Git 根路径、common-dir 与 `.git` 指针路径只移除输出换行，不裁剪合法路径空格。共享目录中只跳过管理目录位于 common-dir 的 `worktrees/<id>` 下、`gitdir` 反向指针匹配、且 `.git` 标记不是符号链接的 linked worktree 记录；归属路径缺失、独立仓库、复制或链接 `.git` 指针、在仓库外自建双向指针的活动记录阻断。当前工作树专属目录的未知 schema 或错配归属也阻断。不采用仅凭可复制的指针放行或增加归属注册表，避免漏掉仍在运行的任务 | `test_git_environment_without_marker_finds_active_common_dir_state`、`test_git_environment_overrides_ancestor_repository_marker`、`test_git_environment_without_managed_state_approves`、`test_invalid_git_environment_without_marker_blocks`、`test_git_timeout_does_not_block_a_git_worktree_without_managed_state`、`test_git_error_still_blocks_a_worktree_with_managed_state`、`test_dangling_git_symlink_blocks_instead_of_approving`、`test_trailing_space_in_git_root_does_not_hide_active_run_from_subdirectory`、`test_trailing_space_in_separate_git_dir_does_not_hide_active_run`、`test_active_state_with_unsupported_schema_is_not_approved`、`test_active_state_in_this_workspace_directory_cannot_claim_another_workspace`、`test_malformed_active_state_from_a_sibling_worktree_does_not_block`、`test_shared_active_state_with_an_unverified_other_owner_blocks`、`test_forged_linked_worktree_pointer_cannot_hide_shared_active_state`、`test_unregistered_worktree_admin_cannot_hide_shared_active_state` |
| [Git 环境变量](https://git-scm.com/docs/git)、HumanLayer 控制面 | 显式 `GIT_DIR` 指向的工作树若不包含 Hook `cwd`，不把该 Git 根当作 `cwd` 的身份，也不提前丢弃 `cwd` 本地或标记目录中的活动状态；无受管状态时仍放行，活动状态或无法确认的布局安全阻断。显式修复提示不能在环境变量指定的其他工作树建门禁。不采用新状态注册表或全局扫描，保持判断局限于当前 `cwd` | `test_git_environment_for_another_worktree_does_not_hide_local_active_state`、`test_git_environment_for_another_worktree_does_not_hide_git_active_state`、`test_git_environment_for_another_worktree_with_no_state_approves`、`test_arm_rejects_git_environment_for_another_worktree` |
| [Git 环境变量](https://git-scm.com/docs/git)、[Git 仓库布局](https://git-scm.com/docs/gitrepository-layout)、HumanLayer 控制面 | 采用沿 `cwd` 到显式工作树根目录检查更近的 `.git` 标记，并核对根目录自身标记与环境变量的 common-dir 是否一致。标记冲突时，Stop 只看当前内层仓库的状态：内层活动运行阻断，内层无状态即使外层活动也放行；显式修复提示不允许误向外层建门禁。不采用全局扫描、注册表或覆盖宿主 Git 环境，因为局部归属检查已覆盖本次真实失败 | `test_outer_git_environment_does_not_hide_nested_repository_active_state`、`test_outer_git_environment_without_nested_repository_state_approves`、`test_foreign_git_dir_cannot_hide_state_at_explicit_worktree_root`、`test_outer_active_state_does_not_block_unmanaged_nested_repository`、`test_matching_git_environment_with_worktree_marker_keeps_active_state`、`test_arm_rejects_outer_git_environment_for_nested_repository`、`test_arm_rejects_foreign_git_dir_at_explicit_worktree_root` |
| HumanLayer 单写者边界与旧租约兼容 | 采用只隔离路径上明确无关的损坏 Git 指针；可能属于当前 worktree 的旧租约仍阻断。写租约身份保留 Git 根路径末尾空格，悬空 `.git` 链接不能绕过工作树核验。不采用任一旧租约读取失败都阻断所有工作区，避免一个坏记录扩大故障域；也不新增租约索引 | `test_unrelated_legacy_lease_with_broken_git_pointer_does_not_block_acquire`、`test_broken_legacy_lease_inside_current_worktree_still_blocks_acquire`、`test_git_root_with_trailing_space_keeps_one_workspace_identity`、`test_dangling_git_symlink_does_not_bypass_workspace_verification` |
| 宿主 Prompt Hook 的显式触发边界 | 非 Git cwd 不接管普通对话；已有 `.git` 标记（包括悬空符号链接）但 Git 查询失败时阻断，不能把故障当作用户未授权或成功跳过；Git 根路径或独立管理目录末尾空格不应被源码取证、状态定位或 repo 身份误删；不另增状态或 Hook | `test_non_git_prompt_does_not_block_an_unrelated_host_task`、`test_git_query_failure_does_not_silently_skip_the_repair_gate`、`test_dangling_git_symlink_blocks_explicit_repair_prompt`、`test_trailing_space_in_git_root_still_arms_repair_gate`、`test_trailing_space_in_separate_git_dir_arms_in_real_common_dir` |

精确“继续修复”提示本身没有结构化 finding；自动创建的 manifest 只承诺后续全范围审计和验证，不能据此宣称已绑定上一轮审查中的每条具体 finding。若要强制逐项绑定，需宿主提供可核对的审查记录或引入显式录入步骤，本轮不伪造该输入。

`git init --separate-git-dir` 创建的主工作树没有可核对的 `gitdir` 反向指针；其共享状态出现在另一个 linked worktree 的 Hook 扫描中时，保守阻断而非推定为无关状态。当前不新增归属注册表，也不把可复制的 `.git` 指针当作证明；对应测试为 `test_separate_git_dir_without_owner_backlink_fails_closed`。
