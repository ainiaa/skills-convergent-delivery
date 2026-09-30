# Converge 自进化参考备忘

> 状态：周度证据复核默认关闭；SkillOpt 候选训练仍需明确授权
>
> 复核日期：2026-09-29

本文规定 Converge 的可选周度证据复核和 SkillOpt 离线候选流程。周度复核由默认关闭的 Codex heartbeat 触发，只检查持久化缺陷与评估证据、报告候选；不会自动训练或修改 Skill。任何现有 Skill、helper、状态机或 hook 都不得借此自动学习、扩大写权或修改评估规则。

## 目标与非目标

手动离线优化只解决一个问题：把重复出现、已有客观证据的交付失败，受控地转成更好的 Skill 规则、helper 或 reference，并证明它能迁移到未见场景。

不做以下事情：

- 每次任务结束都后台总结或修改 Skill；
- 从一次成功或一次主观反馈直接推广全局规则；
- 让 candidate 修改本轮 judge、catalog、eval dataset 或晋升条件；
- 新建与 Single State、Git、defect 文档重复的 memory bank、事件总线或长期守护进程；
- 自动修改 `AGENTS.md`、全局配置、发布、push、merge 或安装内容。

## 参考矩阵

| 参考 | 借鉴机制 | 当前不采用 |
|---|---|---|
| [Tencent SkillHone](https://github.com/Tencent/SkillHone) | Skill 与 Eval 通过代码路径/权限硬隔离；whole-skill 原子变更；held-out 验收；决策历史 | Forgejo、Wiki、完整 issue/PR 控制面 |
| [Skill Distillation](https://github.com/agulli/skills-evolve/blob/main/skills/evolve/skill-distillation/SKILL.md) | 重复轨迹后再提炼；拒绝 `n=1`；在两个未见实例验证迁移；检查 Skill 重叠 | 自动从所有会话生成新 Skill |
| [AutoSkill](https://github.com/ECNU-ICALK/AutoSkill) | `discard / improve / merge / create` 决策分类；先搜索相似能力 | 向量库、代理服务、独立 SkillBank runtime |
| [Skill RSI](https://github.com/justinwetch/Skill-RSI) | 一次只改变一个假设；champion/control 与 challenger/candidate 同场景比较；保留 dead end | 递归自治循环、UI、长期模型运行 |
| [self-improving-agent](https://github.com/zhaono1/agent-playbook/blob/main/skills/self-improving-agent/SKILL.md) | capture-first；晋升审批；置信度、应用次数和退休机制 | 全局 hooks、多层 memory、每次完成或报错自动触发 |
| [Skill SE Kit](https://github.com/d-wwei/skill-se-kit) | governed proposal；`ADD / MERGE / SUPERSEDE / DISCARD`；快照后再变更 | manifest、skill bank、experience、audit、snapshots 五套持久目录 |
| [OpenAI/DeerFlow skill-creator](https://github.com/bytedance/deer-flow/blob/main/skills/public/skill-creator/SKILL.md) | baseline 对照、多样本、blind comparison、train/held-out 分离、无进展停止 | 浏览器 viewer 与特定 CLI 运行时耦合 |
| [Darwin Skill](https://github.com/alchaincyf/darwin-skill) | 每轮只验证一个变更假设；同一 judge 成对比较 control/candidate；奇数独立样本多数表决；保留 keep/revert 证据 | 自动 commit/revert、`results.tsv` 第二真源、连续自修改循环和可被措辞游戏的通用九维打分 |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) 与 Superpowers `writing-skills` | 用真实行为用例验证 Skill 规则；保留对照与 held-out 评估 | Claude CLI、子代理和 HTML viewer 专属执行器 |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/tree/main/skills/design-control-loop) | 周期传感、证据判断、低噪声报告与人类把关 | 每轮自动修改并创建 PR 的 actuator |
| [Microsoft SkillOpt](https://github.com/microsoft/SkillOpt) | 显式离线候选优化；将失败分类为 `SKILL_DEFECT` 或 `EXECUTION_LAPSE`；严格 held-out gate | nightly/sleep 会话采集、运行时自动优化和自动晋升；不把 SkillOpt 设为生产依赖 |

安装量只用于发现，不作为采用依据。采用前仍需检查原始 `SKILL.md`、脚本、测试和宿主能力。

## 每周 Skill 改进证据复核（默认关闭）

- 全局配置路径为 `~/.convergent-delivery/skill-improvement.toml`，项目配置路径为 `.convergent-delivery/skill-improvement.toml`。项目级显式配置优先；项目配置缺失或未设置 `skill_review.enabled` 时继承全局值；两边都没有显式值时关闭。

  全局启用示例：

  ```toml
  [skill_review]
  enabled = true
  ```

  仅对单个项目关闭时，在项目配置写入 `enabled = false`；该值会覆盖全局 `true`。

- Codex 每周 heartbeat 首先运行 `rtk python3 scripts/skillopt_policy.py`。结果为 `skip` 时不得读取评估或缺陷内容；配置无效时安全停止并报告配置错误。
- 开启后只检查 `docs/04_testing/defects/`、`references/evaluation-catalog.json`、`references/evaluation-scenarios.md` 与 `evals/` 中的持久化证据。不得挖掘原始对话、日志、转录或环境变量。
- 有新证据且呈现可复用的 Skill 问题时，只报告问题、证据和候选方向；没有新增或可行动证据时保持安静。同一 heartbeat 线程的上次复核摘要只用于避免重复报告。
- 周度开关只允许证据复核；不启动 SkillOpt 训练，不编辑 Skill、judge、catalog、eval 或其他仓库文件。真实候选优化仍须用户明确请求并通过下述离线验收。

本次控制面决定：项目级显式值优先，缺失时继承全局显式值；两边都缺失时关闭。项目或当前生效的全局配置畸形时 fail closed。行为测试见 `scripts/test_skillopt_policy.py`；周度边界见 `scripts/test_skill_contracts.py`。

## 手动 SkillOpt 试验

- 本次重复循环归类为 `EXECUTION_LAPSE`：同会话审查后的修复规则早已存在，历史行为仍停在只读报告并等待用户再次催修。修补触发描述和多轮验收属于确定性修复；它本身不代表 SkillOpt 候选已经通过模型评测。
- 仅用户明确要求时运行一次 SkillOpt 优化；一次只提出一个假设，先冻结 control、judge 和 held-out，再生成候选并按原评估器成对比较。未通过 held-out 时丢弃候选。
- 只使用已脱敏的场景输入、diff 与结果摘要；不采集原始会话，也不把会话摘录交给外部 backend。需要原始轨迹时先取得明确授权。
- SkillOpt 的结果只作为候选；必须通过 Converge 自己的行为门禁后再人工采纳。自动追加、自动部署、nightly/sleep 不启用，候选不得自动晋升。
- 当前宿主 smoke 仍需 fresh-host receipt；若拿不到同会话多轮的 host-observed 证据，模型行为状态保持 `uncovered`，不能用文字规则断言替代。

已实现可选 `scripts/skillopt_adapter.py`：显式调用 `adapter_class()` 才导入 SkillOpt，默认拒绝真实 rollout。按官方 EnvAdapter 实现 build_train_env/build_eval_env/rollout/get_task_types，继承 setup/reflect；使用者在 SkillOpt train 与 eval_only 两个 CLI registry 注册返回的类。官方接口参考：https://github.com/microsoft/SkillOpt/blob/main/docs/guide/new-benchmark.md 。初次实现仅以接口契约替身验证。2026-09-30 后续已在临时隔离 venv 安装官方 SkillOpt 0.2.0（commit 79124b37e9a6371e13b753f8bcd7adb1e493ade1），验证真实 EnvAdapter 与训练、评估两个 CLI 注册入口，并实际执行单 epoch、单 step、单编辑预算训练。选择集和训练 hard 均为 1，failure_only 路径没有补丁，保留原 Skill。训练器内部 test 关闭，由独立冻结回放执行全部三类留出场景；三类全部通过。没有候选 diff，故不存在候选晋升或相对改善结论。目标模型通过 app-server 调用，官方训练摘要的零 token 只反映优化器无调用，不能代表目标模型零成本。

宿主回放使用一个 app-server thread，默认 gpt-6.1-sol，最多三个样本、总时限 600 秒、每个检查点一次修复。公开训练场景与 held-out 场景分开；仅合成场景可显式保存轨迹。无进展场景由外部固定判定器持续失败，模型不得修改它；超时或断流标记 uncovered 并停止，不作为训练失败样本。提问计数目前按问号启发式计算，不能替代语义审查。`release_status` 始终保留 uncovered：这套开发回放尚不具备正式隔离 held-out 晋升所需的完整证据。正式候选优化仍须冻结 evaluator、control 和 held-out，单假设、单轮 epoch、单编辑预算，未经独立验收不得晋升。周度开关仍只复核证据，不会自动运行该适配器。

## 最小协议

仅在用户明确授权启动候选优化时执行以下离线闭环；每周复核不能自动进入此流程：

```text
verified defect / repeated correction
  → proposal: DISCARD | IMPROVE | MERGE | CREATE | SUPERSEDE
  → bind source defect, trajectories, affected surfaces, hypothesis
  → human authorization
  → freeze old Controller Snapshot and held-out evaluator
  → change one hypothesis on the smallest skill-folder surface
  → fixed public regression + isolated held-out transfer tests
  → each sample compares control/candidate with the same blind judge; use an odd sample count and majority decision
  → all hard acceptance gates pass; aggregate rubric is triage only
  → promote winner or record dead end
```

优先复用现有真源：

- 失败事实：`docs/04_testing/defects/`；
- 历史回归：`references/evaluation-catalog.json`；
- 版本和死路：Git commit、diff 与变更说明；
- 评估控制面：修改前 Controller Snapshot；
- 实际产物：对应 Skill 文件夹，而不是另一份复制的 SkillBank。

最多只新增一个 proposal schema；在真实需求出现前，不创建 proposal 目录或 helper。

## 晋升与淘汰门禁

- 安全、数据损坏、越权、错误完成等信任边界：一次可靠复现可提出晋升，但仍须独立回归。
- 普通流程经验：至少两个成功轨迹和一次重复失败，或同类问题出现三次；单次样本只记录，不晋升。
- 每个泛化必须由轨迹之间真实变化支持，不从一个样本发明参数化规则。
- 必须至少在两个未见实例上成功，并报告相对 control 的正确率、稳定性、轮数或 token 变化。
- 成对比较的同一 judge 只消除标尺漂移，不代表独立性；必须使用奇数个 fresh、相互独立的 judge/sample 对，并保存每对原始双侧结果。
- candidate 或本轮修改后的 Skill 不得读取、修改或重生成 held-out、judge、catalog；训练场景也不能从 candidate 工作树读取。
- 先 `IMPROVE/MERGE` 已有 Skill；只有触发边界确实不同且 negative-trigger 测试不重叠时才 `CREATE`。
- 连续一次候选没有改善冻结指标即停止；同一假设不得换 judge 后重试。
- 长期不命中、与新协议重复或降低 held-out 表现的规则应 `SUPERSEDE/DISCARD`，避免协议只增不减。

## 必需行为测试

未来实现前至少冻结这些测试，测试不得由 candidate 修改：

1. candidate 无法读取 held-out 输入或修改 judge/catalog/evaluator；
2. 缺少用户授权时 proposal 不能写入 Skill；
3. `n=1` 普通经验只能 capture，不能 promote；
4. 同类 Skill 已存在时默认 merge，不创建近重复入口；
5. candidate 在公开用例提升但 held-out 回归时拒绝晋升；
6. 无改善、重复假设、预算耗尽或连接中断时有限停止；
7. dead end 可检索，下一轮不会重复同一实验；
8. 简单 Converge 任务不增加步骤、文件、worker 或 token。

## 试验启用条件

用户明确授权后才运行候选优化；control、judge 和 held-out 必须先冻结，worker provenance 可追溯，且需有足够的已归类重复轨迹。任何一项未满足时只完成 defect-driven hardening，模型优化结果保持 `uncovered`。本文不会被普通任务自动读取。

## 实际运行后的约束修补

- 同线程回放每轮通过官方 turn/start effort 固定为 medium，避免继承本机 xhigh；三样本批次的总时限仍为 600 秒，未启动的样本记 uncovered。补充独立同条件样本后，有三个不同线程完成带注入缺陷的两轮闭环，不能删除原批次的超时记录。
- 普通场景若需要控制器额外催修，SkillOpt hard=0；最终正确仅给予部分 soft 分数。无进展场景按一次修复后 blocked 判为符合停止契约。
- predictions 下分别保存 conversation.json（仅合成轨迹）与 result.json（宿主身份、写入、验证和结果摘要）。default allow_execute=false 不变，周度开关不会启动训练。
- 实验摘要见 docs/04_testing/defects/evidence/followup-validation-20260930/。这属于开发回归与实际包集成验收，仍不冒充 locked control/candidate 正式晋升证据。
