# 多模型协作

用户明确说“使用多模型配合开发”时启用；普通任务保持原路径。角色是固定契约，Agent 是按需创建的可选运行实例。控制器每次只选择一个下一角色，不执行固定的多模型流水线。

| 角色 | 默认模型 / 推理 | 边界 |
|---|---|---|
| `router` | Terra medium | 选择下一动作，不写代码 |
| `scout` | Terra medium | 收集定点证据，不决定需求 |
| `specifier` | Terra high | 冻结 TaskSpec 与验收 |
| `implementer` | Luna high | 在批准范围内测试先行并修改代码 |
| `verifier` | 工具 | 运行测试、检查 diff；不由模型自证通过 |
| `reviewer` | Terra high | 只读检查规格与实现；高风险时使用新上下文 |
| `adjudicator` | Sol high | 处理语义冲突、范围升级和高风险取舍 |

只有 `implementer` 可以请求工作区写入。同一工作区一次只有一个 implementer。`verifier` 是工具角色，不配置模型画像；模型可以解释失败，但不能替代其测试和源码证据。

## 动态流程

`scripts/role_flow.py` 根据冻结状态返回唯一的下一角色和运行方式：`serial` 复用当前控制上下文，`agent` 只在上下文隔离或独立审查确有收益时创建实例，`tool` 只执行确定性验证。它不会把全部角色塞进每个任务。

```text
Router → Implementer → Verifier

Router → Scout → Specifier → Implementer → Verifier → Reviewer
                           └─证据冲突或越界→ Adjudicator
```

验证失败先回到 `router` 重新选择下一步；出现无法由证据消除的语义冲突时才进入 `adjudicator`。TaskSpec、验收、写入范围和验证命令均已冻结时，模型不得自行扩大范围。验证通过且不需要审查时立即结束。

## 受限 CLI 派发边界

对 `mode=agent`，`scripts/role_dispatch.py` 一律返回 `executor=external_runner`，并携带完整冻结 profile。controller 使用 `scripts/runner_lifecycle.py` 执行单次闭环：先把 launch 原子追加到当前 run 的 ledger，再在 lease 外启动 CLI，最后原子追加 result；launch 已记录而 result 缺失时恢复必须交接或阻塞，不能重派。lifecycle 的 stdout 同时返回一个**仅当前调用有效**的 `output`：`available` 时有受限长度的最终模型文本，`unavailable` 时不得以成功 exit code 猜测内容。账本只写 `result` receipt，绝不写 `output`、prompt、密钥或审查原文。controller 必须先将 `output` 转为既有结构化 evidence/review 输入并核验，不能因模型文本自行推进验收或状态。Codex 的 `codex_exec_runner.py` 与 Claude 的 `claude_exec_runner.py` 都由冻结的 profile 驱动受限 CLI：显式传入 model、reasoning effort 和工作区边界，且不依赖父会话模型、不创建宿主原生子代理，也不伪造宿主任务树或完成回执。

当前 Codex CLI 没有可验证的轮次上限参数：不把 `max_turns` 伪称为 Codex CLI 已强制的限制；Codex 仅强制 timeout 与输出字节上限。Claude CLI 接收冻结的 `--max-turns`。`max_turns` 仍保留在统一 profile 中供 controller 规划和跨 runner 比较，但 Codex 上的超时才是实际的有限执行边界。

本地 runner workspace 由当前 run state 派生，调用方不能另传目录：读写角色都只能在 state 的 workspace 工作；`implementer` 因而要求该 run 本身已在独立 Git worktree。`shell=false` 的统一含义是“没有可写工作区的 shell 能力”，不是两套 CLI 都不存在任何命令执行：Codex 在 `read-only` sandbox 内仍可能运行只读命令；Claude 则限制为 `--tools Read,Grep,Glob`。Codex 以 sandbox 强制边界，Claude 使用 `--bare --strict-mcp-config --input-format text`、冻结工具与 `acceptEdits`，不把它表述为 OS sandbox。`mode=serial` 明确复用当前 controller，`mode=tool` 只运行确定性验证。

本地 CLI receipt 的 `requested_model` 与 `requested_reasoning_effort` 只证明冻结命令的请求参数与退出/输出摘要；它不证明远端最终实际采用的模型或 effort。需要审计该事实时，必须有 provider 响应或宿主原生观察，不能由本地进程回执推断。

`inline`、`serial` 与 `tool` 路径不创建 lifecycle、launch 或 runner ledger 记录；现有非多模型流程不经过该入口。未来只有宿主确实可证明精确模型选择、稳定 worker ref、查询和 workspace binding 时，才可作为同一契约的 native transport；当前不伪造该能力。

## 配置

配置支持命名 profile；默认选择 `default_profile`。`schema_version: 4` 必须为六个模型角色完整指定模型与推理等级：

```json
{
  "schema_version": 4,
  "default_profile": "default",
  "profiles": {
    "default": {
      "router": {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
      "scout": {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
      "specifier": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
      "implementer": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
      "reviewer": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
      "adjudicator": {"model": "gpt-5.6-sol", "reasoning_effort": "high"}
    }
  }
}
```

配置优先级为显式 `--config`、项目 `.converge/multi-model.json`、用户级 `~/.convergent-delivery/multi-model.json`、内置默认。模板命令：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" config
```

在 Claude Code 宿主中选择内置映射：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" resolve --profile claude-code
```

仅支持 `schema_version: 4`。旧的 v3 固定流水线配置会明确失败；使用 `multi_model.py config` 输出新模板后直接替换即可。

单次任务可覆盖模型角色，例如：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" resolve \
  --role implementer=gpt-5.6-luna@max \
  --role adjudicator=gpt-5.6-sol@high
```

`max` 是实施遇到已证实难点时的升级档，不是默认流程。只有 `reviewer=glm-5.2@high` 支持外部只读审查；`multi_model.py audit --execute` 仍需显式执行授权，并且不保存 prompt、密钥或审查文本到正式回执。

每个模型角色的 profile 冻结 requested/effective model、推理等级、权限和预算。模型结论不能替代真实测试、源码指纹或发布授权；宿主无法真实指定或查询 worker 时应交接，不能伪造派发。
