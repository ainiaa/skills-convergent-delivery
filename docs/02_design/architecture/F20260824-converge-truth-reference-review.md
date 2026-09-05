# Converge 0.20 外部机制复核

本轮按受影响能力先从 Skills.sh/GitHub 发现近期实现，再核对原始 Skill、脚本与测试。安装量只用于发现；最终只采用能关闭已复现失败、且有本地行为测试的最小机制。

## 2026-09-05 Batch 与覆盖率验收修复

本次沿用同一会话审查中已核对的 Skills.sh 发现结果及原始材料，不重复加载完整第三方流程。

| 参考 | 采用 / 不采用 | 原因与行为验证 |
|---|---|---|
| [Trail of Bits property-based-testing](https://github.com/trailofbits/skills/blob/master/plugins/property-based-testing/skills/property-based-testing/SKILL.md) | 采用参数组合与状态不变量；不新增测试依赖 | `test_native_tdd_policy.py` 覆盖重复、顺序、禁用与有效边界；`test_batch_state.py` 验证合法后续修改不损坏历史 checkpoint |
| [LangChain calibration](https://github.com/langchain-ai/langchain-skills/blob/main/config/skills/eval-engineering/references/calibration.md) | 采用验收器误拒绝/误放行反例；不增加模型数量 | 两批真实 Git 提交应完成；未提交的验证内容不能冒充旧提交，提交也不能增加未验证文件 |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 采用测量可被关闭的检查；不增加定时控制器和记忆文件 | collect-only、cov-reset、Vitest 未启用和 Gradle 排除检查任务都不能返回 ready |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) / [WalkingLabs harness-creator](https://github.com/walkinglabs/learn-harness-engineering/blob/main/skills/harness-creator/SKILL.md) | 保留旧 Controller Snapshot，区分结构测试与真实行为；不复制额外状态文件或结构评分门禁 | 原状态、Source Receipt 与 Git checkpoint 足够承载修复；本地回归不冒充缺失 bridge 的正式 Eval |

实现取舍：直接读取不可变 Git tree/blob 与对应配置，复用现有 delegate、TDD 和 Evidence 校验；不切换工作区、不新增 checkout/状态 schema/代理。暂停或后续批次修改不会使历史回执失效；当前回执与最终验收仍检查源码一致性。

| 参考 | 采用 | 原因与本地行为测试 |
|---|---|---|
| [OpenAI evaluate-skill](https://github.com/openai/plugins/blob/main/plugins/plugin-eval/skills/evaluate-skill/SKILL.md) | control/candidate 同场景差分、冻结判定面 | `test_eval_kernel.py` 验证 Git 双侧来源、同一 judge 和差分统计 |
| [skilltest](https://github.com/lorenzosaraiva/skilltest) | 实际调用 selector、hard negatives、confusion matrix 与 F1 | `test_trigger_evals.py` 证明 runner 真正执行选择命令，不再只验 JSON 形状 |
| [agent-skill-eval](https://github.com/tardigrde/agent-skill-eval) | 记录 eval 数据、runner 与执行配置身份，先完整预检再花费模型调用 | `trigger_eval.py` 在执行前拒绝全部畸形 case，并输出 dataset/selector/runner 指纹；不引入其多后端依赖与工作区协议 |
| [skill-eval-harness](https://github.com/adewale/skill-eval-harness) | 借鉴 trigger negative control、隔离控制面和可复现来源 | 现有 Eval v3 与 Controller Snapshot 已覆盖冻结与隔离；不复制其完整 benchmark/telemetry 层，待真实跨模型比较成为验收项再引入 |
| [Skills.sh: code-review-axes-and-quality](https://www.skills.sh/skynight137/agent-skills/code-review-axes-and-quality) | 不采用额外 durable plan 与 delegation 层 | Converge 已有 Plan v5、Review v3 和单一状态真源；重复引入 `.agents/plans` 会增加第二套可写进度与恢复歧义 |
| [agent-skill-architect](https://github.com/sebastianwessel/skills/blob/main/skills/agent-skill-architect/SKILL.md) | 采用 trigger near-miss、渐进披露与风险化闸门原则 | 现有 `evals/evals.json` 保留 hard negatives，根 Skill 只路由到按需 references；未采用另一套 package scaffold |
| [Maestro](https://github.com/ReinaMacCredy/maestro) | `doctor/status` 可恢复入口、风险等级过低必须阻断 | `test_delivery_state.py` 覆盖 workspace 发现；`test_delivery_next.py` 覆盖 route/scope/risk drift |
| [OpenAI Agents Python code-change-verification](https://github.com/openai/openai-agents-python/blob/main/.agents/skills/code-change-verification/SKILL.md) | 单一 wrapper、fail-fast、命令真实退出码 | `test_evidence_contract.py` 覆盖不存在命令、argv 无 shell 执行和篡改回执 |
| [Harness engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/harness-engineering/SKILL.md) / [Evaluation](https://github.com/guanyang/open-agent-hub/blob/main/skills/evaluation/SKILL.md) | 冻结来源、判定器与证据 provenance | Eval v3 绑定 Git tree、judge bytes、worker observation 与 touched paths |
| [Harness Protocol](https://github.com/harnessprotocol/harness-protocol/blob/main/protocol/profile-schema.md) | 不采用新的通用 profile 协议 | 现有 Task Profile 已足够；只新增 canonical receipt，避免第二套状态和转换层 |
| [自进化参考备忘](self-improving.md) | 仅保留研究与未来门禁设计，不启用运行时 | 补充 Darwin 的成对同 judge 比较与 SkillOpt 的 held-out 晋升；当前不增加自动自改循环、后台 hook、自动 commit/revert 或第二套状态真源 |
| [OpenAI Codex compaction issue](https://github.com/openai/codex/issues/32169) | 不新增 conversation snapshot 日志 | Single State + Source/Controller Snapshot 已覆盖恢复真源；新增对话日志会形成第二真相 |

保留的边界：不新增依赖、DAG、消息总线、签名服务或后台守护进程。同一系统用户仍可直接篡改本地文件；本轮目标是让正常控制路径不能靠自由文本、任意 SHA 或未执行命令误完成，不宣称提供对本机恶意用户的密码学防护。

## 2026-08-25 Skill 优化复核

| 参考 | 采用 / 不采用 | 原因与对应行为测试 |
|---|---|---|
| [OpenAI Build skills](https://developers.openai.com/codex/skills/) / [Agent Skills specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx) | 保持“发现 → 激活 → 按需 reference”的渐进披露；不增加入口 Skill | 全量 `SKILL.md` 会在激活时进入上下文，复杂细节只在需要时读 reference；`test_skill_contracts.py` 与“触发隔离”压力场景覆盖入口边界 |
| [Superpowers writing/testing skills](https://github.com/obra/superpowers/tree/main/skills/writing-skills) | 采用带真实压力与反合理化的独立前向评测；不复制完整 workflow | `converge-eval` 的 frozen control/candidate、history 和 exploration 已是承载面；“真实触发评测”“局部高风险”场景必须由独立 evaluator 执行 |
| [grill-with-docs](https://www.skills.sh/mattpocock/skills/grill-with-docs) / [Wayfinder](https://www.skills.sh/mattpocock/skills/wayfinder) | 只在业务、公共契约或不可逆决定未闭合时先形成一个决策；不默认生成文档或 issue | “业务歧义”场景输出 `blocked_decision`；已消歧的局部高风险任务保持 `inline`，避免为澄清引入固定 token/文件成本 |
| [handoff](https://www.skills.sh/mattpocock/skills/handoff) / [Ralph](https://github.com/iannuttall/ralph) | 使用已有 plan/diff/receipt 的指针与“无新证据即停止”；不新增 handoff ledger、循环状态或后台 agent | Single State、Source Receipt 和有限 repair budget 已为唯一真源；“根因无进展”“清场屏障”场景覆盖停止与交接 |
| 宿主 bridge / [Darwin Skill](https://github.com/alchaincyf/darwin-skill) / [Microsoft SkillOpt](https://github.com/microsoft/SkillOpt) | active worker 必须先有 `host_observed` Binding；将来的显式离线优化才采用单变量、成对比较、held-out gate 与人工晋升 | `test_runtime_adapter.py` 拒绝 controller-attested 伪造 host receipt；`test_delivery_next.py` 拒绝其登记 active worker。`self-improving.md` 的未来门禁要求冻结 control、held-out、奇数独立成对样本和 hard acceptance；当前没有自动写入路径 |
| [gstack domain skills](https://github.com/garrytan/gstack/blob/main/docs/domain-skills.md) | 不采用运行时沉淀/自动晋升；仅保留“隔离 → 重复有效使用 → 显式全局晋升”的未来研究约束 | Converge 的当前任务不需要跨项目记忆；新增 JSONL 和记忆状态会违反 Single State，未来若授权记忆须先通过隔离和 prompt-injection 审计 |

最终收敛路径：先按拓扑而非风险决定 `inline/planned/delegated/batch`；风险独立提高验证与 review；无真实宿主桥接时只手工交接；触发评测必须运行真实 selector；自进化只在用户显式授权的离线实验中进行。新增机制必须先证明减少真实失败或总 token，不能只增加协议。


## 2026-09-05 自治落盘、最终验收与派发身份修复

复用本会话 Skills.sh 发现结果并核对以下原始材料，只采纳本轮边界需要的机制。

| 参考 | 采用 / 不采用及原因 | 对应行为测试 |
|---|---|---|
| [planning-with-files plan-doctor](https://github.com/othmanadi/planning-with-files/blob/master/skills/planning-with-files/scripts/plan-doctor.sh) | 采用真实恢复探测与规范路径；不复制 Markdown 状态或其诊断总是成功退出的策略，现有机器状态负责恢复 | `test_autonomy_service.py` 在真实源码变化和状态写入后恢复 running/observed，未知执行不重放 |
| [Superpowers systematic-debugging](https://github.com/obra/superpowers/blob/master/skills/systematic-debugging/SKILL.md) | 采用跨组件边界追踪；不新增调试控制器 | 自治测试只模拟外部 runner，结果、异常、verifier 失败均走真实落盘与租约释放 |
| [LangChain calibration](https://github.com/langchain-ai/langchain-skills/blob/main/config/skills/eval-engineering/references/calibration.md) | 采用误放行/误拒绝反例；不增加模型数量或独立状态 | `test_batch_state.py` 拒绝文本、缺失、失败与篡改回执，接受当前源码真实验证 |
| [Trail of Bits property-based-testing](https://github.com/trailofbits/skills/blob/master/plugins/property-based-testing/skills/property-based-testing/SKILL.md) | 采用不变量思路，以现有 unittest 参数化有限状态；不引入新测试依赖 | 最终 criterion 从初始化冻结；`test_capsule_dispatch.py` 覆盖所有缓存状态的 workspace 绑定与同路径复用 |
| [Context compression evaluation](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/context-compression/references/evaluation-framework.md) | 采用恢复后核对范围与下一动作；不增加压缩日志或第二份真源 | 恢复依然检查状态身份、冻结约束与租约，只有未完成动作允许旧源码快照 |

复用 Source Receipt、Evidence Receipt、review rounds 和现有 receipt 文件。控制器保有写权、验证与终态清场责任；失败和未知结果有限停止。本轮没有新增代理、依赖、循环或状态文件。真实宿主 Eval bridge 和本仓原生覆盖率配置仍缺失，本地回归不冒充正式 Eval 或覆盖率通过。
