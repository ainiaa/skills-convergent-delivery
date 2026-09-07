# 已知问题修复计划

作者：Jeff.Liu

先计划，再按 T1–T8 顺序执行测试先行的小步修复。机器计划见同目录 `F20260905-known-issues-fix-plan.json`。

## 范围与基线

保留当前所有未提交及未跟踪文件；在现有实现上修复，不回滚用户修改。基线 commit：`5a46384a0b81fc460a4d4ccf00ef5a54e9eade85`。旧控制器快照已在修改前冻结，描述符：`/tmp/converge-known-fixes-control.json`。不调用真实模型，不提交、推送或安装。当前宿主不具备可信叶子 worker lifecycle，独立模型差分评测标为 uncovered，不能用本地测试冒充。

## 修复顺序与验收

| 任务 | 结果 | 关键验收 | 状态 |
|---|---|---|---|
| T1 | 允许合法源码变化后的状态推进 | 旧状态按历史证据校验，新候选按当前源码校验；陈旧候选、错误 revision、错误身份仍拒绝 | 完成 |
| T2 | 单写入 runner 正常登记且只读扇出边界不变 | 单个 implementer launch 可登记；扇出含写权限仍拒绝，未知结果禁止重派 | 完成 |
| T3 | runner 整体执行受统一超时约束 | 父进程退出后子进程持管道仍有限返回 timeout；成功、启动异常、输出超限及进程组清理保持有效 | 完成 |
| T4 | core 审查路径与扩展授权一致 | core 不要求只有多模型扩展才能产生的回执；显式多模型路径继续强制绑定真实审查结果；不放宽高风险验收或伪造独立审查 | 完成 |
| T5 | CI 在干净环境中执行同一校验 | 缺少本机官方 validator 时 CI 有明确可复现准备；validator 不可用时仍失败，不跳过校验 | 完成 |
| T6 | 仓库评测冻结起点且拒绝样例投机 | 提交修改后的测试也不能逃过范围检查；常量实现不能通过正常、边界及异常验收；实现验证与拓扑执行完整性分别报告 | 完成 |
| T7 | 单上下文进度包含当前动作和验证摘要 | 无 worker 时仍输出控制器阶段、下一步和验证；复用已有状态；进度去重和 worker 显示保持有效 | 完成 |
| T8 | 全部修复组合验证并记录限制 | 全部定向回归与全量检查通过；用户已有修改保留；未执行真实模型评估明确标注 | 完成 |

每项先记录失败测试，再最小修复、定向验证。T8 运行 `bash scripts/check.sh --full` 和 `git diff --check`。若发现实现选择会改变公共契约或现有权限边界，先记录具体方案及影响，不通过降低判定标准制造通过。

## 第三方机制取舍

| 参考 | 采用 / 不采用 | 原因 | 行为验证 |
|---|---|---|---|
| [OpenAI skill-creator](/Users/liuwenyuan/.codex/skills/.system/skill-creator/SKILL.md) | 采用最小、风险相称修复；不新增通用协议 | 本轮是已知缺陷修复 | 原有边界及回归均通过 |
| [Superpowers writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) | 采用先失败后修复；不扩大固定流程 | 规则是否执行必须可观测 | T1/T2/T3 真实 CLI 或进程回归 |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) | 采用冻结对照和区分指标可信度；不将输出字符估算成 token | 保持证据真实 | T6 常量实现、篡改测试、失败审查探针 |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 采用本地最小组合路径；不新增控制器 | 组件绿不代表组合可用 | T8 集成回归 |
| [planning-with-files](https://github.com/othmanadi/planning-with-files/blob/master/skills/planning-with-files/SKILL.md) | 采用恢复摘要；不引入三份可写进度文件 | 现有 Single State 足够 | T7 无 worker、恢复、去重 |
| [Context Engineering multi-agent-patterns](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/multi-agent-patterns/SKILL.md) | 保持单控制器；不增加代理拓扑 | 解决当前失败无需新代理 | 不引入额外派发 |

## 后续优化，未计入本轮完成标准

普通计划与全量收口矩阵解耦、规则消融评测、状态构造 API、引用按章节加载、真实宿主近邻触发评测。这些需要独立的契约和行为比较，不与 bugfix 混改。

## 验证记录

执行中更新本节，记录失败与通过命令及未覆盖项。

- T1：真实临时 Git 仓库复现历史 Source Receipt 阻断；修复后新候选仍严格校验当前源码。组合探针同时复现结果回执丢失，允许已冻结 launch 的结果落盘但不刷新陈旧验证；新的 launch 仍被阻止。
- T2：单个 implementer 登记原先失败，现通过；只读扇出写权限和未知 launch 重派仍拒绝。
- T3：两个真实 Python 子进程探针原先各约 4 秒且错误 completed；现约 1 秒 timed_out，包含进程及 I/O 截止时间。两个 runner 共用执行/清场逻辑。
- T4：冻结 core 快照原先无法导入 lifecycle，core reviewer 原先被扩展门禁拒绝；现复用单个本地只读 reviewer。保留 spec/quality、独立盲审、request binding 与实际执行授权。新增必要调用文件纳入 T4 范围，未新增代理或工作流。
- T5：CI 固定 openai/skills commit 49f948faa9258a0c61caceaf225e179651397431 和 validator SHA-256；缺失校验器仍失败。未安装任何依赖。
- T6：常量答案、提交隐藏测试修改、失败或缺失 reviewer 的回归均先失败；新增正常、边界、异常样例并分开报告实现验收和拓扑完整性。判定器改动只作为本地诊断修复，旧 locked evaluator 未改写，不宣称独立模型评测通过。
- T7：无 worker 进度原先只有 Git 统计；现从已有 handoff 派生目标、阶段、最近验证记录、待处理和下一步；重新加载、revision 更新去重以及状态只读测试通过。

- T5 补充：从 PATH 移除真实 Codex/Claude 后，旧 CLI 参数测试失败；check 入口现提供仅退出 127 的临时客户端替身，并在退出时清理。本地 CLI reviewer 测试已纳入 core 默认检查。
- T8 组合场景：真实 managed state、writer lease、CLI 启动和回执落盘依次完成 spec/quality，最终写入 complete。模型输出由本地 Python fixture 生成，此测试证明控制链连通，不证明模型审查质量。

## 最终结果

T1–T8 的代码修复和本地验证完成。Plan v6 校验输出 `valid / sequential`，不需要本地 commit 授权。最终在 PATH 仅保留 Python 与系统工具（无真实 Codex、Claude、CodeGraph）的环境中，使用 CI 固定版本的官方 validator 执行 `bash scripts/check.sh --full`：退出码 0，53 组测试、745 项测试，零失败，输出 `All checks passed.`。日志位于 `/tmp/converge-known-fixes-clean-full-check.log`。`git diff --check` 通过。

CI 环境发现的额外依赖已消除：模型 CLI 使用拒绝执行的临时测试替身；图谱回执测试用显式进程 fixture 验证 query / scope / fingerprint 绑定，不代表已验证真实图谱提取质量。按需导入网络 runner 后，旧测试 mock 改为替换原定义模块，结果断言未删减。

修改前冻结的控制器快照通过 `validate_launch_snapshot` 及其原始校验器验证。真实宿主独立模型差分评测仍为 `uncovered`；未调用真实模型、未安装依赖、未提交或推送。计划范围外原有 6 个修改文件已逐个对照基线内容摘要，保持不变。前述矩阵分层、规则消融、状态 API 等契约优化继续保留在后续项，本轮不宣称已实现。
