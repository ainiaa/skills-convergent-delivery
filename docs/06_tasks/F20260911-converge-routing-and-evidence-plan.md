# Converge 路由与证据闭环优化计划（v1，已由下方 v2 取代）

## 目标与边界

处理一次实际失败模式：跨服务、公共 API 的状态机任务被错误标为 `local/single/low` 后走了 inline；指定参考没有在首次写入前冻结为可核对的行为依据；依赖缺失导致的同一验证失败被重复尝试，并被误说成完成。

本计划只加强现有 Converge 控制路径，不增加新代理、后台循环、第二状态或自动发布。它不能阻止绕过 Skill/控制器的直接宿主写入；该边界由宿主权限隔离和 CI 负责。

## 已决事项

| ID | 决定 | 依据 |
| --- | --- | --- |
| D1 | `cross-service` 风险与 `local` scope、`single` coupling、`local` verification 的任一组合均拒绝冻结；使用跨服务 scope、依赖 coupling 和非本地验证才能路由。 | 实际误路由；可逆技术约束。 |
| D2 | 用户明确指定的参考必须先实际读取，按参考列出状态/输入→输出→副作用的行为矩阵；未决业务映射先阻塞，不根据同名实现猜测。 | 根 Skill 已声明的引用真源与决策门禁。 |
| D3 | 同一 diff、同一冻结 verifier 的失败不得重跑；首次失败进入 `blocked`，没有新 source/evidence 不得称“已验证”或“完成”。 | 现有有限循环与 evidence-first 规则。 |

## 参考机制记录

| 受影响能力 | 采用 | 不采用 | 行为验证 |
| --- | --- | --- | --- |
| Skill 触发与渐进披露 | 采用 Anthropic skill-creator 的明确 trigger/按需参考；把硬门禁前置到根 Skill。 | 不扩充长篇流程或新增 Skill。 | 静态 Skill 契约 + interaction scenario。 |
| 有限计划切片 | 采用 Superpowers writing-plans 的单结果、TDD、依赖顺序。 | 不使用其 subagent-per-task 拓扑；共享工作区仍顺序执行。 | 本计划 T1→T2→T3 与每项定向回归。 |
| TDD/证据 | 采用现有 Source/Evidence Receipt 与“验证失败即停止”。 | 不引入新日志或证据数据库。 | task_profile、reference_receipt、interaction smoke 回归。 |
| 长循环与控制面 | 采用 HumanLayer 的确定性人工门禁原则和本仓已有 one-repair/block 语义。 | 不新增外层自动重试或守护进程。 | 失败/未决情景只能 `not_complete`。 |

外部原始材料：Anthropic `skill-creator`、Superpowers `writing-plans`/`executing-plans`、HumanLayer control-loop；均只采纳上述可测试机制。

## 有限任务

### T1 — 拒绝跨服务画像矛盾

- 范围：`scripts/task_profile.py`、`scripts/test_task_profile.py`、`references/task-routing.md`。
- 先添加失败测试：带 `cross-service` 风险却仍为 `local/single/local` 的画像必须被拒绝；合法跨服务画像必须仍确定路由为 `planned`。
- 最小实现：在现有 `classify` 校验中加入一致性检查，不改变真正局部高风险任务的 inline 语义。
- 验收：矛盾画像无法冻结；跨服务任务不能进入 inline。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_task_profile`。

### T2 — 把指定参考与业务歧义提到首次写入前

- 依赖：T1。
- 范围：`SKILL.md`、`references/task-routing.md`、`references/execution-protocol.md`、`scripts/test_skill_contracts.py`。
- 先添加失败契约：根入口必须要求执行并检查画像；指定实现参考须读后形成行为矩阵；映射/重试等业务歧义必须先走单一决策门禁。
- 最小实现：只强化已有 reference receipt / routing / decision 规则的可见、顺序明确的指令；不增加持久化状态。
- 验收：跨服务公开契约不会凭 “低风险” 进入 inline；无法读取参考或未决映射不允许首次业务写入。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_skill_contracts scripts.test_reference_receipt`。

### T3 — 把重复失败和无证据完成纳入回放评测

- 依赖：T2。
- 范围：`scripts/interaction_smoke.py`、`scripts/test_interaction_contract.py`、`evals/converge-interaction-v1.json`、`CHANGELOG.md`。
- 先添加失败测试：目录必须包含“跨服务参考任务”和“同一 verifier 被环境阻塞”的关键场景；两者都只能 `not_complete`，后者不能由重复尝试变成完成。
- 最小实现：扩展既有 interaction catalog 的枚举和关键集，不创造另一套执行器。
- 验收：新鲜宿主 smoke 的回执只有有真实验证时才可 `verified_only`；阻塞场景保持 `not_complete`。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_interaction_contract scripts.test_interaction_smoke`，随后运行 `bash scripts/check.sh --full`。

## 终态

每项只完成一次红绿与定向回归；若业务映射仍未由参考或用户决定，停在 `blocked`，不进入后续实现。最终报告将区分确定性回归与尚未执行的真实宿主 smoke。

---

# v2：工作项续跑与功能级参考绑定

## 结果与边界

在 v1 已有的路由/证据修正上，补齐两个缺口：参考精确绑定到同项目的**目标功能**和**参考功能**；只有需跨轮修复的 `active` / `blocked` 工作项才持久化。一次性 inline 保持无状态、无后台循环、无新增代理。

机制仅约束经过 Converge 控制器的任务；绕过控制器的宿主写入仍由权限隔离和 CI 负责。它不自动复制参考、不猜测业务映射、不自动重试同一失败，也不发布。

## 已决设计

| ID | 决定 | 原因 |
| --- | --- | --- |
| D1 | 工作项 key 由仓库、冻结基线、目标功能、验收和已决需求生成；唯一 `active/blocked` 项恢复，零个新建，多个匹配项阻塞。 | 工作项而非项目拥有续跑状态。 |
| D2 | `reference_receipt` 形成 feature binding：目标、参考、关系（`mirror` / `analogy` / `negative`）、内容指纹和行为矩阵同一 immutable contract。 | 参考只约束声明的行为。 |
| D3 | 每条矩阵冻结输入、前置状态、输出/副作用、调用面、验证命令；不能确定的映射进入单一 `decision` 阻塞。 | 写入前冻结公共语义。 |
| D4 | 保存 verifier 的 `argv + source_fingerprint + failed receipt fingerprint`；相同三元组直接 blocked，只有源码、命令或恢复证据改变才能新尝试。 | 有限退出，环境失败不伪装为完成。 |
| D5 | 仅非终态工作项持久化，复用 managed-state root、私有原子写和 lease；binding 嵌入工作项，不另建可写 ledger。 | 满足恢复而不加重简单路径。 |

## 外部机制采用记录

| 能力 | 采用 | 不采用 | 行为验证 |
| --- | --- | --- | --- |
| Skill 渐进披露 | Anthropic [skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) 的明确 trigger/按需读取。 | 新 Skill 或常驻流程。 | 一次性 inline 不创建工作项。 |
| 有限执行 | Superpowers [writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md) 的单结果/顺序，以及 [executing-plans](https://github.com/obra/superpowers/blob/main/skills/executing-plans/SKILL.md) 的重复失败停止。 | 每任务子代理、并发写。 | 相同 verifier/source 失败拒绝重跑。 |
| 状态与恢复 | 复用本仓 revision、lease、原子私有写，并采纳 HumanLayer [control-loop](https://github.com/humanlayer/skills) 的人工决策边界。 | 项目级全局进度、后台守护。 | 唯一项恢复；歧义/未决阻塞。 |
| 新鲜证据 | Superpowers [verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) 与现有 Evidence Receipt。 | 口头声明、旧日志、同一失败重跑完成。 | 只有当前源码的新鲜成功回执可完成。 |

## 顺序任务

### T1 — 冻结功能级参考行为

- 范围：`scripts/reference_receipt.py`、`scripts/test_reference_receipt.py`、`scripts/runner_launch.py`、`scripts/test_runner_launch.py`。
- 先写失败测试：feature binding 必须有唯一 target/reference/relation 和完整矩阵；未读参考、空矩阵、重复 target、非法关系拒绝；旧 receipt 可读。
- 最小实现：扩展既有 receipt 严格 schema 与兼容读取；launch 只接受完整已读 binding。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_reference_receipt scripts.test_runner_launch`。

### T2 — 只为可续跑工作项持久化 contract

- 依赖：T1；范围：新增 `scripts/work_item.py` / `scripts/test_work_item.py`，以及最小的 `SKILL.md`、`references/execution-protocol.md` 说明。
- 先写失败测试：完成 inline 不落盘；唯一 active/blocked key 可恢复；不同功能/验收不碰撞；多候选或未决 decision 阻塞；binding、acceptance、baseline 不可篡改。
- 最小实现：工作项是唯一恢复真源，复用 managed root、原子私有写、revision、lease；不复用自治阶段机、不启动服务。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_work_item scripts.test_delivery_state`。

### T3 — 失败去重、恢复门禁、交互评测

- 依赖：T2；范围：`scripts/work_item.py` / 测试、现有 interaction catalog/contract/smoke、根 Skill/路由协议、`CHANGELOG.md`。
- 先写失败测试：相同 verifier/source/failure receipt 不再调度；只有源码、argv、recovery receipt 变化可新尝试；无新鲜成功回执绝不 complete；未满足 feature binding/decision 只能 blocked。
- 最小实现：把 attempt fingerprint 写入工作项，并对齐 v1 跨服务路由场景；不建第二执行器。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_work_item scripts.test_interaction_contract scripts.test_interaction_smoke scripts.test_skill_contracts`，随后 `bash scripts/check.sh --full`。

### T4 — 收口

- 依赖：T3；只修复上述验证暴露的同一机制缺口。
- 验收：定向测试、新鲜全量检查、`git diff --check` 均通过；未运行的真实宿主 smoke 明确是 `uncovered`。

按 `same_session` 顺序执行 T1 → T2 → T3 → T4。任何业务语义、公共 API 或功能关系无法由用户/参考确定时，只提出一个 `decision` 并停止，不以技术默认越过。

---

# v3：一次性收口剩余工作项控制缺口

v2 的结构与格式校验已落地；本节冻结审查发现的运行时缺口，并取代 v2 的未完成项。

## 已决边界

| ID | 决定 | 可验证结果 |
| --- | --- | --- |
| D6 | schema v2 回执中，工作项 `target` 必须恰好对应一个 feature binding；无 feature binding 的 schema v1 回执继续用于没有功能级参考的任务。 | A 功能的回执不能创建或恢复 B 功能事项。 |
| D7 | 恢复必须同时匹配 workspace、baseline、target、requirements、acceptance、decisions 与 reference receipt fingerprint。任一不符均明确阻塞，而不是复用旧事项或新建相似事项。 | 续跑不会静默丢失已决语义或切换起点。 |
| D8 | 受控验证必须使用事项冻结的 workspace/baseline；不同调用者输入先失败，绝不启动 verifier。改变基线需要显式的新事项/后续 rebase 机制，本轮不暗中迁移。 | 事项 A 不能拿事项 B 的源码或基线运行。 |
| D9 | `verify` 与 Python API 都接收并校验 observed passing recovery receipt；它只解除同一 source+argv 的失败去重，不能作为完成证据。 | 文档承诺的恢复路径真实可达，重复失败仍有限停止。 |

## 本轮有限任务

### T1 — 绑定与恢复语义守卫

- 先写失败测试：错误 target 的 schema v2 receipt、不同 decision、不同 receipt 或不同 baseline 的恢复全部拒绝；完全相同 contract 才恢复。
- 最小实现：在现有 receipt/work item 边界比较冻结值，不增加项目级 ledger、自动 rebase 或后台进程。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_work_item scripts.test_reference_receipt`。

### T2 — 受控 verifier 的调用与恢复回执

- 先写失败测试：workspace/baseline 不匹配时 `run_work_item_evidence` 不触发 runner；`verify --recovery-receipt` 能以有效 observed pass 解除 gate，伪造或失败 receipt 仍拒绝。
- 最小实现：在同一个 work-item 模块传递 recovery receipt；不开放直接 argv 执行，也不把 recovery 视为成功交付。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_work_item`，并保留一个真实 CLI 受控命令回执。

### T3 — 协议、交互契约与收口

- 更新 root Skill、执行协议、交互目录与 changelog，使“精确 feature binding / 全 contract 恢复 / recovery CLI / 校验边界”可由自动测试发现倒退。
- 最终验证：定向 suite、`bash scripts/check.sh --full`、覆盖率 gate、`git diff --check`。真实宿主隔离仍不是此 Python wrapper 可证明的能力，报告为边界而非完成证据。

按 `same_session` 顺序执行 T1 → T2 → T3；任一未知业务语义仍停在一个明确的 decision，不以本计划替用户推断。
