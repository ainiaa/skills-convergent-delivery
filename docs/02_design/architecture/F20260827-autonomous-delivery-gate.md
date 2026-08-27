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

Stop Hook 是显式、可撤销的 adapter，而非默认安装项。Codex 使用本机 `codex queue --thread` 将 gate 的下一动作投递到同一 task，同一 stage/action 不能由 metadata-only revision 重新投递；Claude Code 2.1.246+ 直接返回 `decision:block` 与下一动作，让宿主继续同一会话。`--autonomy` 先运行本机 preflight，预检失败拒绝注册；不得从 Claude Hook 另起 `--resume` 进程，因为宿主拒绝同时写入同一 transcript。native v11 无 finding 路径至多五次、一次 finding 修复至多七次连续 Stop continuation，均低于 Claude 的八次硬上限。普通验证仅在临时 HOME 测试配置合并、适配器输入输出、Codex queue 参数与 Claude 原生 block 决策；它不安装真实全局 Hook、不调用模型，也不宣称验证了宿主真实回调。目标宿主中的 live smoke 必须由用户另行选择。

Codex `queue` 只能投递到当前可寻址 task；Claude Stop continuation 同样不承诺后台、跨会话或掉线后的自主恢复。需要该能力时，用户可显式启用 macOS `autonomy-service`：它使用 state 中冻结的外部 CLI runner 和 verifier argv，在独立隔离 worktree 中逐动作执行。每个动作先落盘 intent/running，模型回执仅形成 observed，独立 verifier 成功后才 committed；重启发现 running 则按未知结果 block，绝不盲目重放。service 只有用户显式冻结 `audit_findings_exit_code` 时才把该 audit exit 解释为可修复 finding，其他非零仍为阻塞。重启扫描会幂等清理已写终态但未释放的 lease；永久无效 state 只输出一次诊断并成功退出，避免 LaunchAgent 重启循环。service 与 Hook continuation 互斥。找不到 Codex `session_id`、队列失败或已有多个 active run 都必须保持有证据的 blocked/handoff，而不是创建新会话。

## 交付、暂停与恢复

- 启用：用户明确闭环执行；如需 Stop Hook，再显式安装 `--autonomy`。
- 暂停：用户停止、权限/不可逆动作或宿主能力不足，状态记录为 `blocked`/decision 与 `handoff`。
- 恢复：同一 run 使用 writer lease、revision、冻结 manifest 和最新证据继续；旧 Schema v10 不会被静默升级为 v11。
- 卸载：`--autonomy-uninstall` 只移除本 Skill 精确注册的 Hook command，保留状态与其他 Hook。
- 结束：`delivery_report.py` 只从已验证状态、当前范围 audit 和 Evidence Receipt 生成报告；审计摘要不保存模型 transcript。

## 验收

固定 15 条以上的无 transcript 轨迹目录覆盖：完整修复、新 finding、重复失败、陈旧证据、范围/风险漂移、决策/权限门禁、用户停止、宿主不支持、多 run 与恢复交接。完整套件不执行真实模型、Hook 安装或外发操作。
