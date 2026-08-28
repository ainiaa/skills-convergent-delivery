# Converge 0.0.21 控制面与多模型 runner 加固记录

本轮只处理已复现且会影响完成可信度或子任务效率的控制面缺口；不增加后台守护进程、持久队列、第二状态库或自动自改循环。

| 问题 / 参考能力 | 采用的最小机制 | 行为验收 | 未采用与原因 |
|---|---|---|---|
| 宿主能力不能靠自由布尔值放行 | `negotiate` 与 `bind` 仅产出 `controller_attested`；只有 `bind_observed` 可接受 query id、时间、profile 与 canonical capabilities 的完整原始桥接观察；Schema v4 绑定原始 observation 和 fingerprint；Codex profile 静态禁止 activity/process/resume | `scripts/test_runtime_adapter.py`：全 true Codex 仍 terminal-only；generic bind 无法构造 host-observed | 不引入签名服务或 runtime daemon：本地同权进程不能获得密码学来源保证，冻结 controller + 原始桥接回执已关闭正常路径误放行 |
| 超时建议未落到宿主调用 | watchdog 返回受 `run_contract.py` 校验的 `query|wait|interrupt|block`，始终绑定 task/worker；不支持 wait 时退回 query | `scripts/test_runtime_adapter.py`：terminal-only 只 wait/query，observed 才 interrupt | 不另建 scheduler：控制器已有唯一派发权和 worker registry |
| 子任务被中断前丢失上下文 | observed soft probe 前固化已有 milestone/source/verification 为 partial handoff；它不代表完成，也不触发重派 | `references/execution-control.md` 与 runtime action 测试：无活动证据前不 interrupt | 不增加 worker partial-state 字段：现有 `progress`/handoff 已是同一状态真源，新增可写日志会制造双重事实 |
| 计划将 TBD 误当已决 | Plan v6 拒绝标准占位 resolution | `skills/converge-plan/scripts/test_plan_check.py` | 不限制真实技术决策自由文本，只拒绝无决策标记 |
| trigger eval 只指纹 argv | selector descriptor 绑定 argv 与实际 artifact 内容 sha256 | `scripts/test_trigger_evals.py`：修改 selector 文件会改变 fingerprint | 不加入多后端 eval harness，当前真实执行+F1 已覆盖目标 |
| 评测证据可在 candidate tree 内伪造、registry 顺序敏感 | Sample v4 强制候选仓库外的 absolute evaluator-attested artifact；registry 比较使用集合 | `skills/converge-eval/scripts/test_eval_kernel.py` | 不宣称 evidence 是 host-signed：当前宿主没有可验证的 evaluator-output artifact API |
| 老快照继续执行旧安全规则 | Controller Protocol v12 阻止旧快照执行，唯一兼容动作是释放自身 lease | `scripts/test_controller_snapshot.py` | 不热修已冻结脚本：会破坏快照可审计性 |
| 简单任务加载无关控制细节 | 根入口仅在非 inline/worker/recovery 路径读取 execution-control | `scripts/test_skill_contracts.py` | 不拆出新入口 skill，现有渐进披露已足够 |
| fast path 可为语义文档签发 receipt | 通用 fast path 已停用；Git 空白 diff 不能证明 Markdown 等文档无语义变化 | 路由契约测试：所有改动进入完整路径 | 仅在未来提供 formatter 专属且可验证的语义安全 contract 时重新开放 |
| 不同 worker 可能临时变更模型、effort 或权限 | Worker Profile v1 冻结 requested/effective model、effort、权限与有限预算；静态 registry 只暴露 Codex CLI 和只读 OpenAI-compatible 两种 runner | `scripts/test_worker_profile.py`、`scripts/test_runner_registry.py` | 不引入通用 agent framework、broker 或第二状态：控制器已有计划、lease 和完成门禁 |
| 外部 CLI/API leaf 容易伪装成宿主 subagent | Codex launch 和 OpenAI-compatible HTTPS request 默认仅计划，真实执行要显式 opt-in；receipt 明确标为 `runner`，不进入 `runtime_binding`/`host_observed` | `scripts/test_codex_exec_runner.py`、`scripts/test_openai_compatible_runner.py` | 不伪造 Codex Desktop host bridge：宿主未公开 selector/tree receipt 前，runner 结果仍由 controller 复核 |

外部取舍：Agent Skills 的 discovery → activation → execution 三段渐进披露支持按需读取 references；SkillHone 的“整 skill 文件夹、隔离评测、held-out gate”支持本轮将脚本、契约和文档作为同一候选改动，但其 Forgejo/持续优化服务超出当前任务。`external-subagents` 验证了用 `codex exec --json` 驱动外部 leaf 的可行性，但其独立 metadata/state 不进入本项目。模型参数以官方接口为准：OpenAI 的 [model/effort 指南](https://developers.openai.com/api/docs/guides/latest-model)、[DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [GLM 5.2 / OpenAI-compatible 指南](https://docs.bigmodel.cn/cn/guide/develop/others)。参考：[Agent Skills](https://github.com/agentskills/agentskills/blob/main/docs/home.mdx)、[SkillHone](https://github.com/Tencent/SkillHone)、[external-subagents](https://github.com/obra/external-subagents)。

## 2026-08-26 Review 可恢复性与指标边界

| 参考能力 | 采用 / 不采用 | 原因与对应行为测试 |
|---|---|---|
| [Skill Creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) / [Superpowers writing skills](https://github.com/obra/superpowers-skills/blob/main/skills/meta/writing-skills/SKILL.md) | 采用“先失败测试、最小可观察契约”的更新方式 | `test_review_contract.py` 先证明 finding 正在丢失，再验证 adapter 保留有界 `finding_records`；`test_delivery_next.py` 验证状态 round 只接受与 fingerprint 一致的记录。 |
| Review 恢复 | 在现有 Review v3 request 内保存有界结构化 finding；不采用独立 finding ledger | 当前 round 已不可变且有 append-only transition；新增可写台账会制造第二真相。`test_delivery_next.py` 同时覆盖匹配接受和篡改拒绝。 |
| Review 独立性 | `independent` 指 fresh reviewer 独立于实现者；spec 通过后可复用同一 reviewer 处理 blind quality，不采用每轴额外 worker | Protocol 的“全新上下文”排除实现理由和完整实现会话，不要求两轴各建上下文；现有状态机绑定有序单轴请求。`test_delivery_next.py` 覆盖同 reviewer 的有效状态，`test_review_axes_contract.py` 锁定 fresh-context 表述。 |
| 语义风险 | 将 `risk_flags` 明确为冻结前的语义风险声明，路径扫描只作下限；不增加“自动语义扫描器” | 通用文本/代码扫描无法可靠判定金额、权限或兼容性语义，反而可能虚假降级；`test_task_profile.py` 保持任一已声明风险进入 high review，`test_skill_contracts.py` 锁定该边界说明。 |
| [Harness Protocol](https://github.com/harnessprotocol/harness-protocol/blob/main/protocol/profile-schema.md) / 宿主 metrics | 只汇总已签名 runner 回执内的 `usage.total_tokens`；工具调用、用户阻塞及宿主未公开指标显式为 unavailable，不采用估算或模拟 bridge | `test_delivery_report.py` 验证 token 只来自签名 receipt；`test_runtime_adapter.py` 与 bridge 缺失压力场景继续拒绝伪造 `host_observed`。 |

## 2026-08-28 全量收口声明

| 参考能力 | 采用 / 不采用 | 原因与对应行为测试 |
|---|---|---|
| [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | 采用“完成声明必须由最后变更后的证据支撑” | Plan v6 将 `final_acceptance` 映射到强制 closure matrix，`plan_check.py audit --require-complete` 因 `uncovered` 确定性失败；而不是把“测试全绿”当作全量完成。 |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) / [Superpowers writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) | 采用失败契约测试和真实近似触发场景 | 先让 `test_universal_completion_claims_require_a_finite_closure_matrix` 失败，再加入入口规则、矩阵和压力场景；不把关键词断言误称为独立模型评测。 |
| Review 与 Plan 的跨状态绑定 | 不新增仅供声明的 `closure_matrix_fingerprint` 字段 | 当前 Single State 的 Review 已绑定同一源码、验收与允许范围；Plan audit 已绑定同一 Source Receipt 与矩阵。两者之间没有可执行的计划执行器可消费该字段，持久化它只会制造第二份可伪造、不可验证的真相。改以 v3 Routing Receipt 阻止全量请求绕开 Plan，且以 Plan matrix v3 的 Source/调用面投影回执阻止其在执行中漂移；`test_task_profile.py`、`test_autonomy_begin.py`、`test_plan_check.py` 覆盖该闭环。 |
| 独立 coverage 数据库、第二状态机、无限“再检查一次”循环 | 不采用 | Plan 已有任务、验收和审计真源；新增可写台账会产生双重事实，重复扫描也不能证明不存在未知 bug。矩阵限定输入/冻结/副作用/回执/恢复，并将无法覆盖处如实标为 `uncovered`。 |
