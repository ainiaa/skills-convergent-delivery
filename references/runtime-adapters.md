# 自治 Stop Hook 适配

本文件只描述 Schema v11 自治交付的宿主薄适配器；worker 的 Runtime Adapter 仍以 [Batch Runtime Adapters](../skills/converge-batch/references/runtime-adapters.md) 为准。

## 启用与撤销

普通安装不会写入 Hook。用户明确要求闭环执行，且本机预检通过后，才可执行：

```bash
bash install.sh --target <codex|claude> --autonomy
```

安装器只加入自己的精确 command，原子写入并保留同一配置中的其他 Hook。撤销使用：

```bash
bash install.sh --autonomy-uninstall --target <codex|claude>
```

这不会删除状态、Skill 或其他 Hook。Codex CLI 的 `queue --thread` 将下一动作投递回同一 task；Claude Code 2.1.246+ 使用原生 Stop Hook `decision:block` 在同一会话继续，不能从 Hook 另起 `--resume` 进程（同一 transcript 同时写入会被宿主拒绝）。预检验证 Codex command/queue 或 Claude 版本/adapter 可执行，不等于真实宿主 Hook 已被触发。真实 smoke 需要用户在目标宿主中明确执行，不能由常规检查代替。

## 持久服务（显式）

`bash install.sh --target codex --autonomy-service` 另行注册 macOS LaunchAgent。用 `autonomy_begin.py --runtime service --service-runner <id> --verification-argv '<JSON argv>' --audit-argv '<JSON argv>'` 创建 low-risk service run；argv 在 arm 时冻结、相互不同，不能是 shell 字符串。语义风险用 `--risk-flag` 声明，与路径风险合并后只要进入 high review tier 就拒绝 service。它只扫描 State 中 `autonomy.runtime.mode=service` 的有效 run；已识别但无效的 active service state 记录诊断并使服务失败退出，但不会阻止同一 state root 中健康 run 执行；直接指定无效 state 返回手工恢复诊断。每次仅以该 state 冻结的 implementer runner 执行一个 gate action：先持久化 `intent → running` 和冻结 runner launch，启动后写入匹配 runner receipt，再记录回执为 `observed`，并实际执行冻结 verifier；controller 使用 verifier 收据原子更新 source receipt 和阶段，再写为 `committed`。最终独立 audit 必须在同一 source 通过，才在同一写入归档验收并记录完整 manifest 的 pass audit；失败 audit 也以 fail check 保存完整 receipt；runner 不能写 managed state。服务和同一 run 的 Hook continuation 互斥：Hook 只唤醒 LaunchAgent，不会再 queue 或 block 当前会话。服务没有任何 active state 时成功退出；进程异常时 LaunchAgent 才重启，因此重启/掉线后的 active service run 可被重新扫描。可写状态的异常会持久化为 blocked；终态 lease 必须返回 `released`，否则服务以手工恢复错误退出；重启发现 `running` 也按未知结果 `blocked/no_progress`，绝不猜测性重放。撤销使用 `bash install.sh --target codex --autonomy-service-uninstall`。

## 决策语义

Hook 从 stdin 读取宿主提供的 `cwd`。仅当 `~/.convergent-delivery/state/` 中存在唯一的、同 workspace 的 Schema v11 `active` run 才接管 Stop：

- `autonomy_gate.py` 返回下一 action：Codex Hook 使用 `codex queue --thread <session>` 将该 action 投递回当前 task；同一 state path、revision 和 action 只能成功投递一次，重复 Stop 而状态未变会以 `no state progress` 阻断，绝不再次 queue。该私有回执只记录 revision 与 action fingerprint，不是任务状态、也不保存 prompt/transcript。Claude Hook 返回 `decision:block` 与同一 action，由宿主继续当前会话，并由宿主的连续 Stop 上限兜底。控制器只执行该动作后再进入下一轮。
- 状态经过 gate 验证为 `complete` 或 `blocked`：Hook approve，控制器生成由 `delivery_report.py` 派生的最终报告。
- 多个 run、状态损坏、scope/risk 漂移或证据不新鲜：block 并写明可恢复原因。
- 没有 run、非自治 run 或无效宿主 payload：approve，不干扰普通任务。

Hook 不执行模型命令、不写任务状态、不保存 prompt/transcript，也不能创建后台恢复。Codex 必须收到宿主 `session_id`，否则拒绝把 active run 伪装为完成；Claude 原生 Stop continuation 不需要新进程或额外 session ID。native v11 正常路径最多五次连续续跑，低于 Claude 的八次宿主保护上限；未推进 state 的 Codex run 在一次投递后停止自动续跑。用户停止、权限/不可逆决策、没有进展或宿主能力缺失必须按现有状态机进入 `blocked` 或 decision gate。

## Arm

用户明确闭环后，controller 从已验证的 active Schema v10 state 生成候选 v11 状态。`autonomy_arm.py` 默认只输出候选；显式 `--write` 时必须提供既有 lease、state root、run/writer/repo/task 和 expected revision，并委托 `delivery_state.py write` 以同一 CAS 原子落盘。它必须带至少一个 requirement 与 acceptance，scope 自动来自既有 frozen routing；缺任何写入身份或比较版本即拒绝，所以旧状态不会被静默升级。
