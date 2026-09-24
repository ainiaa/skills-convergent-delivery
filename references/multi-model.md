# 多模型协作

用户明确说“使用多模型配合开发”时启用；普通任务保持原路径。角色是固定契约，Agent 是按需创建的可选运行实例。控制器每次只选择一个下一角色，不执行固定的多模型流水线。

这是选择性外部 runner 扩展，不是完整的角色级模型编排。在常规 `role_flow` 路径，只有 `agent` 角色有模型 profile；`serial` 复用当前 controller，不切换模型，也不产生 runner lifecycle。当前默认流中，`reviewer` 会使用 `agent`，`scout` 和 `implementer` 仅在已证明上下文隔离收益时使用 `agent`；`router`、`specifier` 与 `adjudicator` 是 controller 角色，不接受模型覆盖。

`desktop-task` 和 `audit --execute` 是显式的直接入口，不经过 `role_flow`：前者只用 implementer profile 生成 host 的模型请求，后者只用 GLM reviewer profile 发起一次诊断请求。两者各自的 receipt 语义仍适用，不能伪装为 `runner_lifecycle` 的常规角色执行或远端模型已观察事实。

| 角色 | 内置画像 / 推理 | 边界 |
|---|---|---|
| `router` | 当前 controller（串行） | 选择下一动作，不写代码 |
| `scout` | GPT-6 Luna medium | 收集定点证据，不决定需求 |
| `specifier` | 当前 controller（串行） | 冻结 TaskSpec 与验收 |
| `implementer` | GPT-6 Sol high | 在批准范围内测试先行并修改代码 |
| `verifier` | 工具 | 运行测试、检查 diff；不由模型自证通过 |
| `reviewer` | GPT-6 Sol high | 只读检查规格与实现；高风险时使用新上下文 |
| `adjudicator` | 当前 controller（串行） | 处理语义冲突、范围升级和高风险取舍 |

只有 `implementer` 可以请求工作区写入。同一工作区一次只有一个 implementer。`verifier` 是工具角色，不配置模型画像；模型可以解释失败，但不能替代其测试和源码证据。

这是一套按角色绑定模型的协作配置，不是多模型投票或共识系统。重复 fan-out 的同一角色复用同一冻结 profile；它们的独立性只来自任务范围和上下文，不能宣称获得了不同模型的独立判断。需要异质性复核时，必须显式选择不同的角色 profile 或单独授权外部只读审计，并以验收与工具证据裁决，不能由票数放行。

只读角色的新结果使用 v2：每一项 evidence 都是 `{kind, reference, content_fingerprint}`，其中 `kind` 为 `file`、`command`、`url` 或 `artifact`，且 content fingerprint 必须是 SHA-256 形状。`file` 必须包含仓库相对路径和正行号，URL 仅允许 HTTPS。该 fingerprint 只是模型结论中受格式约束的声明，尚未由控制器重算或获取，不能当作 observed Evidence Receipt，也不能单独推进验收；原始模型回答不进入 ledger。为了恢复旧 run，已持久化的 v1 字符串 evidence 仍可校验，但新 launch 不会再产生 v1 结果。

## 动态流程

`scripts/role_flow.py` 根据冻结状态返回唯一的下一角色和运行方式：`serial` 复用当前控制上下文，`agent` 只在上下文隔离或独立审查确有收益时创建实例，`tool` 只执行确定性验证。它不会把全部角色塞进每个任务。

```text
Router → Implementer → Verifier

Router → Scout → Specifier → Implementer → Verifier → Reviewer
                           └─证据冲突或越界→ Adjudicator
```

验证失败先回到 `router` 重新选择下一步；出现无法由证据消除的语义冲突时才进入 `adjudicator`。TaskSpec、验收、写入范围和验证命令均已冻结时，模型不得自行扩大范围。验证通过且不需要审查时立即结束。

## 受限 CLI 派发边界

只有 `agent` 模式的 `scripts/role_dispatch.py` 会返回 `executor=external_runner`，并携带完整冻结 profile。controller 使用 `scripts/runner_lifecycle.py` 执行单次闭环：它先验证 dispatch role 与当前 managed-state stage 相符，并要求 implementer 的 run 位于独立 Git worktree；之后才把 launch 原子追加到当前 run 的 ledger，再在 lease 外启动 CLI，最后把 receipt 与已校验的 `role_result` 作为**同一条** `runner_results` 记录原子追加；launch 已记录而 result 缺失时恢复必须交接或阻塞，不能重派。runner 的低层 `output` 仅在当前调用内短暂存在；lifecycle 对只读的 scout/reviewer 把它按固定 JSON 契约转换为带 launch 指纹的 `role_result`，不返回原文。空输出、非 JSON 或字段不合规都会显式标为 `unavailable`/`invalid`，不能由成功 exit code 猜测内容；implementer 也不会被误当作只读结论生产者。账本绝不写 `output`、prompt、密钥或审查原文；已完成的只读 receipt 若缺少绑定的 `role_result`，恢复会阻止下一次 dispatch 并要求交接，不能补猜或自动重派。后续 controller 必须核验 `role_result` 后才可将其转换为既有 structured evidence/review 输入，且其本身不能推进验收或状态。Codex 的 `codex_exec_runner.py` 与 Claude 的 `claude_exec_runner.py` 都由冻结的 profile 驱动受限 CLI：显式传入 model、reasoning effort 和工作区边界，且不依赖父会话模型、不创建宿主原生子代理，也不伪造宿主任务树或完成回执。

当前 Codex CLI 没有可验证的轮次上限参数：不把 `max_turns` 伪称为 Codex CLI 已强制的限制；Codex 仅强制 timeout 与输出字节上限。Claude CLI 接收冻结的 `--max-turns`。`max_turns` 仍保留在统一 profile 中供 controller 规划和跨 runner 比较，但 Codex 上的超时才是实际的有限执行边界。

## 受控只读 fan-out

默认仍是单一下一动作。只有 controller 已证明任务彼此独立时，才可调用 `role_dispatch.plan_read_only_fanout` 或 `role_dispatch.py --fanout <tasks.json>` 创建 1–3 个固定 task id 的 scout/reviewer dispatch；任何可写 workspace 或可用 shell 的 profile 都会被拒绝。高风险任务可额外传 `--require-heterogeneous`，此时至少两个 branch 的 `(provider, model)` 必须各不相同；例如用 `--role reviewer=glm-5.2@high` 为 reviewer 选择显式外部只读 profile。默认不会因 fan-out 自动替换模型。`runner_lifecycle.run_fanout` 与 `runner_lifecycle.py --fanout` 消费该冻结 dispatch 和 task-id→prompt 的 JSON 输入：先以一次原子状态更新追加**全部** launch，再并发执行，随后按冻结 task id 顺序追加 receipt 并调用 `role_fanout.fan_in` 汇总。任一 branch 没有 `completed` receipt 或没有 `available` 的结构化结果，fan-in 失败并保持交接阻塞；不会自动重派，也不会把原文、peer 消息或完整会话传给其他 worker。该入口不改动 `role_flow.py` 的默认单角色路径，也不允许并行 implementer 或并行写工作区。

## 行为评测

`references/multi-model-evaluation.json` 固定 16 个只读 scout/reviewer 场景，覆盖四种证据类型和五种 next action。每个场景携带一个冻结的合成证据内容；评测器先重算其 SHA-256，再要求模型只返回对应的唯一 `{kind, reference, content_fingerprint}`，额外或伪造引用同样失败。每个场景只有一个 oracle action，且所有会进入模型 prompt 的字段都不得出现 `next_action` 或该动作词；自定义题库违反该规则会被拒绝。当前评测验证 JSON 合规、给定证据的精确引用、基于证据的路由和用量；合成 URL 仅是离线 fixture，不验证真实网络检索，也不把模型声明当作业务验收证据。默认仅解析配置并输出不含 prompt 的 `planned` 报告；只有显式 `--execute` 才会启动 runner。报告以 schema v3 输出 `scenario_fingerprint`、`evaluator_fingerprint` 和 `controller_fingerprint`；不同指纹的结果不可横向比较，可选 `--output` 应指向评测工件目录而非业务 ledger。

需要把结果用于控制面决策时，必须从已冻结、只读的 Controller Snapshot 脚本运行，并将 `--snapshot-descriptor` 指向该 run 的 managed state 文件（而不是可任意制作的 snapshot JSON）。该模式拒绝自定义题库，验证该 state 的 canonical path 与其中冻结的 snapshot，并报告其聚合 `controller_fingerprint`；直接从候选工作区运行会标记为 `trust_level=diagnostic`，不能作为可信评测回执。

对两个及以上已执行的 snapshot 报告，可用同一评测器的 `--compare-report` 生成横向摘要；它拒绝 controller 或题库指纹不同的报告，并汇总 pass/fail、已执行场景数、提前停止原因、耗时和 provider 已返回的整数 usage 字段。比较产物固定标为 `trust_level=diagnostic`，不得用于控制面放行或模型路由；它不推断 token 价格或货币成本：缺少供应商可审计定价/用量时，报告必须保持该项为空而不是估算。

模型档位校准另复用已有的 `scripts/multi_model_repo_eval.py`，不以以上 16 个合成只读场景推断编码质量。先冻结 2–3 个代表性 Git 任务及正常、边界、异常测试；对同一题库分别执行同模式的 `implementer=gpt-6-sol@medium` 与 `@high`（或明确比较 `single`/`multi`），保存两份报告，再用 `--compare-report` 核对相同的题库与评测器指纹、profile 身份、通过率和耗时。内置的两个小题仅用于评测器 smoke，不代表真实项目质量。执行需要显式 `--allow-execute`；模型成本和人工打断次数没有可审计观测时保持 `uncovered`。未获得真实任务对比前，不因 GPT-6 升级而自动下调 Sol high 或提高 Astra 用量。

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model_eval.py" --workspace "$PWD"
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model_eval.py" --workspace "$PWD" --execute \
  --output /absolute/path/multi-model-eval.json
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model_eval.py" \
  --compare-report /absolute/path/profile-a.json \
  --compare-report /absolute/path/profile-b.json
```

GLM reviewer 评测仍需同时显式配置 `--role reviewer=glm-5.2@high` 与 `--allow-network`；这不会绕过凭据、预算或 runner 的既有网络授权。

## 机制依据（2026-09）

| 参考与决定 | 采用 / 不采用 | 原因 | 行为测试 |
| --- | --- | --- | --- |
| [OpenAI 的代码编排与结构化输出](https://openai.github.io/openai-agents-python/multi_agent/) | 采用类型化、可验证结果 | controller 需要检查输出，而不是转述 agent 对话 | `test_role_result.py` |
| [Anthropic 的小样本评测与隐私观测](https://www.anthropic.com/engineering/multi-agent-research-system) | 采用固定、显式执行的 16 场景评测 | 先测合规、路由和用量，且报告不存 transcript | `test_multi_model_eval.py` |
| [Anthropic 的独立方向研究](https://www.anthropic.com/engineering/multi-agent-research-system) | 采用显式异质只读 fan-out | 对高风险任务降低同构偏差，不扩大写入并发 | `test_role_fanout.py` |
| peer swarm、成员互聊、自动扩容 | 不采用 | 编码任务依赖高；当前目标是可恢复的单写入者控制 | `test_role_flow.py`、`test_runner_lifecycle.py` |
| [Git rev-parse 路径输出](https://git-scm.com/docs/git-rev-parse) | 采用只移除行终止符的隔离 worktree 身份检查；不新增路径注册表 | 合法路径末尾空格不应改变单写入者隔离判定 | `test_writer_accepts_isolated_worktree_with_trailing_space_in_path` |
| [OpenAI 模型选择](https://developers.openai.com/api/docs/guides/model-selection)、[GPT-6 迁移](https://developers.openai.com/api/docs/guides/latest-model) | 采用 GPT-6 Luna/Sol 的实际可派发角色分层；不采用串行 Astra 画像 | 只有 runner 能切换模型；Sol high→medium 须经真实同模式任务对比，不把官方建议当作本仓质量结论 | `test_multi_model.py`、`test_multi_model_repo_eval.py` |
| [OpenAI GPT-6 Skill 指南](https://learn.chatgpt.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)、[skill-creator](https://developers.openai.com/codex/skills) | 采用短入口和按需加载；不新增 GPT-6 专属状态机 | 减少默认上下文与无效角色配置，同时保留既有授权、验证和有限退出边界 | `test_skill_contracts.py`、`test_multi_model.py` |
| [Claude Code 模型别名](https://code.claude.com/docs/en/model-config) | 采用现有 `haiku`/`sonnet`/`opus` 别名；不钉死具体版本 | 别名随宿主与提供方变化，保留显式 profile 与真实 smoke 门槛 | `test_multi_model.py`、`test_multi_model_smoke.py` |
| [多代理模式原始 Skill](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/multi-agent-patterns/SKILL.md)、[Superpowers 原始 Skill](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md) | 不采用每角色常驻或每阶段强制新代理 | 更强模型不构成增加代理的证据；保持单控制器与按需隔离 | `test_role_flow.py`、`test_role_dispatch.py` |

本地 runner workspace 由当前 run state 派生，调用方不能另传目录：读写角色都只能在 state 的 workspace 工作；`implementer` 因而要求该 run 本身已在独立 Git worktree。`shell=false` 的统一含义是“没有可写工作区的 shell 能力”，不是两套 CLI 都不存在任何命令执行：Codex 在 `read-only` sandbox 内仍可能运行只读命令；Claude 则限制为 `--tools Read,Grep,Glob` 与 `plan` permission mode。Codex 以 sandbox 强制边界；Claude 没有可验证的等价 OS sandbox，因此不开放其可写角色。`mode=serial` 明确复用当前 controller，`mode=tool` 只运行确定性验证。

本地 CLI receipt 的 `requested_model` 与 `requested_reasoning_effort` 只证明冻结命令的请求参数与退出/输出摘要；它不证明远端最终实际采用的模型或 effort。需要审计该事实时，必须有 provider 响应或宿主原生观察，不能由本地进程回执推断。

`inline`、`serial` 与 `tool` 路径不创建 lifecycle、launch 或 runner ledger 记录；现有非多模型流程不经过该入口。未来只有宿主确实可证明精确模型选择、稳定 worker ref、查询和 workspace binding 时，才可作为同一契约的 native transport；当前不伪造该能力。

Desktop controller 若实际暴露 `create_thread`、`wait_threads` 与 `set_thread_archived`，可用 `multi_model.py desktop-task --project-id <id> --title <title> --input <prompt>` 生成一次 `desktop-task-v1` 创建动作。controller 提交该动作后，只从实际 `create_thread` 结果生成 receipt、只接受正式 `threadId`、以该精确引用调用 `wait_threads`；归档必须消费由该查询及同一 task ref 绑定的终态 observation，不能接受调用方提供的裸状态字符串。该动作同时绑定已验证的 implementer profile fingerprint、请求的 `model` / `thinking`；它们仍不代表远端实际模型观察。Python 命令本身不会调用宿主、不会进入 `workers[]` lifecycle；完整宿主顺序见 `extensions/converge-multimodel/SKILL.md`。

## 配置

配置支持命名 profile；默认选择 `default_profile`。`schema_version: 4` 新配置只需为三个可派发角色指定模型与推理等级：

```json
{
  "schema_version": 4,
  "default_profile": "default",
  "profiles": {
    "default": {
      "scout": {"model": "gpt-6-luna", "reasoning_effort": "medium"},
      "implementer": {"model": "gpt-6-sol", "reasoning_effort": "high"},
      "reviewer": {"model": "gpt-6-sol", "reasoning_effort": "high"}
    }
  }
}
```

配置优先级为显式 `--config`、项目 `.converge/multi-model.json`、内置默认。仅显式选择 `--profile` 时，才在无项目配置的情况下读取用户级 `~/.convergent-delivery/multi-model.json`；因此本机命名备选 profile 不遮蔽内置默认。模板命令：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" config
```

在 Claude Code 宿主中选择内置映射：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" resolve --profile claude-code
```

`claude-code` 是可选兼容 profile，不携带账号、token 或 Provider 配置。它只用于只读角色；`implementer` 始终使用受 sandbox 约束的 Codex runner。只有在用户环境完成真实 smoke 后，才可将其视为已验收能力；未验收时不阻塞 Codex-only 的发布，也不得在发布说明中声称 Claude 已验证可用。

仅支持 `schema_version: 4`。旧的六角色 v4 配置仍可读取，但 `router`、`specifier`、`adjudicator` 项不再生成可派发 profile；命令行覆盖这三个串行角色会明确报错。本机 `backup` 等旧配置无需改写，实际派发的三个角色继续按其显式值运行；旧 v3 固定流水线配置仍明确失败。Codex profile 支持旧 GPT-5.6 系列及 GPT-6 Astra/Sol/Luna；Claude Code profile 支持 `haiku`、`fable`、`sonnet`、`opus` 及 `claude-*` 标识。模型是否能在具体账号与宿主执行仍需 smoke 验证。

单次任务可覆盖模型角色，例如：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" resolve \
  --role implementer=gpt-6-sol@max \
  --role reviewer=gpt-6-astra@high
```

`max` 是实施遇到已证实难点时的升级档，不是默认流程。审查需要更深推理时可显式覆盖为 `gpt-6-astra@high`；串行 adjudicator 始终继承当前 controller，不再提供虚假的 Astra 模型画像。只有 `reviewer=glm-5.2@high` 支持外部只读审查；`multi_model.py audit --execute` 仍需显式执行授权，并且不保存 prompt、密钥或审查文本到正式回执。它的输出固定标记为 `diagnostic`，不等同 Review v3 或可用于控制面放行。

每个模型角色的 profile 冻结 requested/effective model、推理等级、权限和预算。模型结论不能替代真实测试、源码指纹或发布授权；宿主无法真实指定或查询 worker 时应交接，不能伪造派发。
