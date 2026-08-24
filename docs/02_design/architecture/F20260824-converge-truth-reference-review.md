# Converge 0.20 外部机制复核

本轮按受影响能力先从 Skills.sh/GitHub 发现近期实现，再核对原始 Skill、脚本与测试。安装量只用于发现；最终只采用能关闭已复现失败、且有本地行为测试的最小机制。

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
| [Stellarlink self-evolution](https://github.com/stellarlinkco/skills/blob/main/skills/self-evolution/SKILL.md) | 不采用自动自改循环 | 当前诉求是有限交付；自进化会扩大写权、评估面和停止问题 |
| [OpenAI Codex compaction issue](https://github.com/openai/codex/issues/32169) | 不新增 conversation snapshot 日志 | Single State + Source/Controller Snapshot 已覆盖恢复真源；新增对话日志会形成第二真相 |

保留的边界：不新增依赖、DAG、消息总线、签名服务或后台守护进程。同一系统用户仍可直接篡改本地文件；本轮目标是让正常控制路径不能靠自由文本、任意 SHA 或未执行命令误完成，不宣称提供对本机恶意用户的密码学防护。
