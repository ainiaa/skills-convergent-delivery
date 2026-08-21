# Converge 项目开发约束

## 最终目标

Converge 的价值是让一个已授权的软件任务以尽量少的人为介入、轮数、上下文和代理开销可靠完成，并留下可核对的结果。实现优先级固定为：

1. 正确完成用户需求；
2. 行为可预测、可停止、可恢复；
3. 执行路径和交互尽可能简单；
4. 使用新鲜客观证据交付；
5. 最后才考虑更多并行、更多代理或更复杂协议。

不得为了协议完备、未来扩展或形式上的自动化增加当前任务不需要的状态、角色、循环、文件或代理。简单任务必须保持简单路径。

## Skill 设计原则

- Converge 是控制器，不重复 Provider 已负责的需求、设计、TDD、实现和阶段审查。
- 默认单上下文、顺序执行；只有上下文隔离或真实独立工作能带来明确收益时才使用代理。
- 派发权集中在当前 run 的控制器。执行、审查和评估 worker 默认是叶子，不得自行派生代理；需要帮助时返回结构化请求，由控制器决定。
- 计划、状态推进、停止条件、完成判定和清场优先由确定性 helper 实现。每次只决定并执行一个下一动作，避免模型一次生成完整长流程。
- 状态只保留恢复、并发安全和验收必需的信息。机器状态是唯一真源；用户进度和最终报告从状态与 Git/验证结果派生，不建立第二套可写真相。
- 循环必须有限：有预算、有客观进展条件、有 stuck/fail stop。没有新证据或同一问题重复时停止，不靠继续采样碰运气。
- 评估器、验收项和判定规则在一次运行内属于 locked surface；候选 Skill 不得修改判定器后给自己放行。
- 发布、推送、合并、删除和其他外发或不可逆动作始终单独授权。

## 外部参考与研究纪律

修改 Converge 的规划、执行、代理、循环、恢复、评估、进度或报告机制前，不得只围绕已经熟悉的 PDLC、Superpowers 或 Matt Pocock 系列做局部类比。先按受影响能力检查下列参考矩阵，并记录“采用 / 不采用 / 原因 / 对应行为测试”。

| 能力 | 优先参考 |
|---|---|
| Skill 触发、渐进披露和行为测试 | Anthropic/OpenAI `skill-creator`、Superpowers `writing-skills` |
| 需求澄清与计划切片 | Grill/Grilling、Superpowers `brainstorming` / `writing-plans`、Matt `to-prd` / `to-issues` |
| TDD、实现和调试 | PDLC、Superpowers TDD / `systematic-debugging`、Matt TDD / `diagnosing-bugs` |
| 多代理拓扑与交接 | Superpowers `subagent-driven-development`、Agent Skills for Context Engineering `multi-agent-patterns`、宿主官方 subagent 文档 |
| 长任务和有限循环 | PDLC loop、ECC `continuous-agent-loop`、Ralph/Ralph TUI、Google Stitch Loop |
| 状态、上下文和恢复 | `planning-with-files`、`filesystem-context`、Ralph TUI |
| Harness 与独立评估 | `harness-engineering`、`evaluation`、`advanced-evaluation`、Superpowers `verification-before-completion` |
| 控制面和人工边界 | HumanLayer `design-control-loop` / `build-iterated-agentic-loop` |
| 交付与交接 | Matt `handoff`、Superpowers ledger/report/review package 模式 |

检索时先看 Skills.sh 对应分类和排行榜，再核对原始 GitHub `SKILL.md`、脚本、测试与宿主官方文档。安装量只能用于发现，不能替代架构和行为证据；复制、二手介绍和仅有文案的 Skill 不作为关键设计依据。

不要全量加载参考 Skill。只读取本次受影响能力需要的材料；广泛调研的结论压缩成机制记录，避免把来源全文塞进实现上下文。

## 评审每个方案时必须回答

1. 这个机制是否真的需要存在，能否复用现有状态或宿主能力？
2. 它减少了哪一种真实失败，而不是只让协议看起来完整？
3. 简单任务是否因此增加步骤、token、文件或代理？
4. 谁拥有决定权、写权和终态清场责任？
5. 失败、无进展、连接中断和用户停止时如何有限退出？
6. 是否有比文档关键词断言更接近真实行为的测试？
7. 是否记录了未采用的成熟方案及原因，避免下一轮重复研究？

如果新增机制不能给出明确答案，默认不实现。
