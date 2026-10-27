# 多模型审查问题修复计划

作者：Jeff.Liu

基线与可执行任务见同目录 `F20261021-multimodel-review-fixes-plan.json`。当前工作区已有变更纳入起点，不回滚、不混作本轮新增。当前控制器已在仓库外冻结；本轮顺序执行，不增加常驻角色、依赖或后台任务。

## 问题归并与验收

| 任务 | 已确认问题 | 可观察验收 |
|---|---|---|
| T1 | 格式失败锁住后续派发；顶层 completed 混淆进程和结果；类型异常覆盖真实 receipt；错误信息不足 | 保留真实退出码与输出指纹，结果无效明确 blocked；只允许绑定原失败 launch 的一次显式格式恢复；保留历史，未知状态和第二次失败不能重派 |
| T2 | API blind reviewer 无源码；凭据缺失污染 run；quality 前置 spec 未检查 | 所有可确定的前置失败发生在 launch 写入前；无源码读取能力的 API 正式审查明确拒绝；quality 必须有同源码 spec pass |
| T3 | started/updated 被当最终文本；冻结快照遗漏多模型 Skill 入口 | 非完成消息不能产生结果；新快照包含启用扩展入口与摘要；历史协议快照仍可读取 |
| T4 | 文档与运行机制、测试之间缺口 | 协议写清恢复和能力边界；故障→恢复→验收的组合测试通过；全量检查及全部生产 Python 90% 覆盖率通过 |

预算耗尽不是独立缺陷；不同根因能否开启下一轮沿用已有规则，本轮不改预算。目标仓库 coverage 缺失属于预检待处理项，本轮不替产品仓库配置或放松门禁。产品 Markdown、HTML 校验缺陷不属于本仓修复范围。

## 执行与停止

每项先跑新增失败测试，再改生产代码，随后运行 JSON 中的验证命令；T4 检查组合路径和全量生产覆盖率。writer、计划推进和终态由当前控制器拥有。进程未知、用户停止、真实无进展或权限决定仍停止；恢复不覆盖原回执、不清零审查预算，不触发自动模型重试。格式恢复仅适用于新协议快照，旧不可变 run 不迁移或改写。

## 机制取舍

| 参考 | 采用 | 不采用与原因 | 对应行为测试 |
|---|---|---|---|
| [Skills.sh writing-skills](https://skills.sh/obra/superpowers/writing-skills)、本机 OpenAI skill-creator 与 Superpowers writing-skills | 用真实解析器与状态门禁构造红灯；保持渐进披露 | 不继续堆叠通用提示词规则；本次根因在共享 helper | 结果类型错误、进程回执保持、恢复次数与边界回归 |
| [多代理上下文模式](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/multi-agent-patterns/SKILL.md) | 单控制器，按 runner 实际工具能力派发 | 不增加模型投票、角色或 context 上传服务；不能凭 workspace=read 推断 API 能读源码 | 无源码 API reviewer 派发前拒绝；本地 reviewer 保持可用 |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 明确观测、下一动作、执行和有限退出 | 不引入调度器、独立反馈账本或无界重启 | 已退出格式失败可清场；unknown 保留租约；最多一次显式恢复 |
| [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | 结论绑定当前测试与源码；复核残留 finding 后才报告 | 不将旧聊天里的测试或一次 smoke 当稳定性证明 | 新鲜全量 gate 与 90% 生产覆盖率 |
| 现有 Controller Snapshot、runner ledger、review request | 复用原始 ledger，仅增加必要的恢复关联 | 不增加第二状态文件、不重写旧 run、不启用新模型或依赖 | 失败 launch 不变；恢复绑定同 profile/request；快照向后兼容 |

采用理由：减少格式故障放大、无材料审查和不可恢复状态；简单 inline 路径不增加步骤、文件或代理。新恢复字段仅保留并发安全、审计和一次性验收所需关联。研究按受影响能力取样；Skills.sh 的 multi-agent-patterns 路由不可用，已核对原始 GitHub Skill，未以安装量作依据。

## 验证记录

### 同事项后续审查

再次检查发现并复现两项同范围问题：最后一条空/非文本完成消息会复用旧回答；前置审查只有 pass 标记而无绑定 runner receipt 也能通过。已先补失败回归，再修正 Codex/Claude 消息解析与 quality/integration 前置绑定。验证覆盖合法回执、缺失/篡改回执、错误 reviewer、陈旧或被后续 finding 覆盖的 spec，以及两个轴到 integration 的组合路径。沿用原计划范围和停止边界，不增加模型调用或重置旧 run 预算。下面原首轮记录保留，后续验证另记。

- T1–T4 已按顺序完成。新增回归先复现类型异常、格式失败锁住派发、前置能力缺口、未完成事件提取和快照漏项，再实施修复。
- 结果与状态定向组 132 项、前置门禁组 63 项、事件/快照组 78 项检查通过；后续独立复核发现 scout 超长数字与 Unicode 逃逸，补红灯后修复并复核关闭。
- 正式 state CLI 的失败→恢复→完成要求组合测试通过；再次失败、未知退出、配置漂移和重复恢复均不放行；CLI blocked 返回非零状态。
- 最终 `python3 -m pytest scripts/test_coverage_gate.py --cov --cov-fail-under=90` 退出码 0：内部完整 `bash scripts/check.sh --full` 通过，全部生产 Python 覆盖率 **90.65%**。未改变 `.coveragerc` 或 90% 门槛；补入原 gate 漏掉的现有适配测试及本次恢复组合测试。
- 验证在干净的可丢弃候选副本执行；逐字核对全部 Python 文件与当前工作区一致，副本内 Git commit 仅为验证夹具，用户仓库没有提交或推送。
- Plan v6 校验与 `git diff --check` 通过；按起点 Source Receipt 比较，本轮新增变更无计划范围漂移，原有脏文件保留。
- 持久验证产物：`.git/convergent-delivery/artifacts/multimodel-review-fixes-20261021/coverage-final.log` 与 `verification.json`（含源码文件摘要）。
- 确定性 Eval preflight ready；真实模型稳定性、冻结模型行为差分和宿主 evaluator lifecycle 仍为 uncovered。未调用真实模型、上传源码、重新安装或迁移旧 blocked run。


后续复核验证：90 项定向检查通过，独立只读复核无剩余可操作问题；最终全量 gate 退出码 0，全部生产 Python 覆盖率 90.65%。原文本块数组兼容保持；不完整的最终消息不得回退旧结论。已保存 `coverage-followup.log`、`focused-followup.log`、`verification-followup.json`；真实模型与宿主验证范围仍为 uncovered。

### 0.10.0 发布前复核

确认并补红灯复现两项恢复边界：环境续接的无效 JSON 被错误地禁止单次格式恢复；旧协议控制器可被选为续接目标，却无法读取写入的新状态。修复复用现有 `recovery_of`、冻结请求和 `validate_recovery_launch`，目标控制器要求当前协议；不新增状态、代理角色或重试预算。组合回归同时拒绝普通重派、错误目标、重复和链式恢复，真实 CLI 拒绝旧目标并保持原状态不变。原始回执及旧控制器身份继续保留。

| 参考 | 采用 / 不采用及原因 | 对应行为测试 |
|---|---|---|
| [Skills.sh filesystem-context](https://skills.sh/?q=filesystem-context)（本轮不可访问）；[原始 filesystem-context](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/filesystem-context/SKILL.md) | 采用已有文件证据和显式引用；不增加平行恢复账本，现有 ledger 足以绑定格式恢复 | `test_environment_recheck_allows_only_one_bound_format_recovery` |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md)；Superpowers TDD / verification-before-completion | 采用先观测失败、最小单步修复、当前源码验证和有限停止；不采用调度器或新循环，两个问题都能由现有门禁解决 | 上述组合回归、`test_real_resume_cli_preserves_receipts_and_rejects_duplicate_or_stale_revision` |
