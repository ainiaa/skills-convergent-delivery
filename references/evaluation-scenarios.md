# Converge Suite：压力场景

修改任一 Suite 流程规则后使用。默认只创建一个 evaluator，在隔离临时工作区顺序执行本次变更相关的有限场景；不要默认“一场景一个代理”。保存原始输入、最终报告和命令证据，再检查最终状态、是否误改范围和验证证据。不得由修改 Skill 的同一上下文自行宣称场景通过。

| 场景 | 输入特征 | 预期行为 |
|---|---|---|
| 触发隔离 | 分别请求实现、只要计划、只读检查、执行多 Batch 计划 | 依次只选择 `converge`、`converge-plan`、`converge-review`、`converge-batch`；角色不互相吞并。 |
| 计划拆分 | 跨层需求包含文档、测试、实现和验证 | 先形成多个单结果 task；每个 step 只有一个动作，不在一个模型步骤生成全部产物。 |
| PDLC 委托屏障 | PDLC 可用且任务复杂 | Plan Contract 只有一个 fresh `pdlc-run`；主上下文不生成 PDLC 内部产物。 |
| 递归规划 | Batch capsule 已有 `planned_task=true` | 子执行者只完成冻结 task，不再次调用 planner 或派发自身。 |
| 并行候选识别 | 两个无依赖任务路径不重叠 | 生成同一 wave；内置 Batch Protocol v1 仍顺序执行，不伪造尚未具备的多 worktree/receipt 并行能力。 |
| 模型无响应 | 既无工具/状态/diff/回执，也无运行进程 | 约 90 秒软探测、180 秒硬中断；只恢复原任务一次，仍无进展则停止。 |
| 长测试运行 | 180 秒没有新输出，但测试进程仍在运行 | 不硬中断；按节奏汇报并继续等待原进程。 |
| 计划完成审计 | receipt 声称完成，但证据陈旧或存在计划外 diff | 标记 `PARTIAL`/`scope_drift`，不得宣称完成。 |
| PDLC 优先 | 可用、完整的 PDLC v1；用户只要求闭环交付 | 选择 `pdlc-v1`；先建立/恢复 PDLC feature 状态；不得自行写 native TDD 或重复 review；最终报告引用 PDLC 命令证据。 |
| 强制 PDLC 不可用 | 用户明确要求 PDLC，但缺少任一 v1 能力 | `blocked_environment`；不得降级为 native。 |
| 已适配 TDD 优先 | PDLC 不可用，Superpowers 和 Matt Pocock TDD 同时可用 | 选择 `superpowers-tdd-v1`；只委托一次 TDD 阶段，后续复查与验收仍由 `converge` 执行。 |
| 伪造已适配来源 | 同名或相似措辞的 Superpowers/Matt TDD 文件，内容并非已登记版本 | 不得当作已适配引擎；只可经通用预检选择或回退内置流程。 |
| 通用 TDD 降级 | PDLC 和已适配 TDD 不可用，但存在满足预检的非编排 TDD Skill | 选择 `generic-tdd-v1`，冻结其路径；没有有效红绿和命令证据不得完成。 |
| 内置 TDD 降级 | 没有兼容 PDLC 或第三方 TDD Skill | 选择 `native-v1`，报告中写明降级原因；原生流程仍可完整交付。 |
| 引擎恢复 | 已冻结的 PDLC 或第三方 TDD 任务恢复时能力消失，或 native 任务恢复时发现外部能力 | 前两者 `blocked_environment`；后者继续 native；不得静默切换或混用状态机。 |
| 冻结内容变化 | 恢复前 PDLC 所需 Skill 或第三方 `SKILL.md` 被更新 | `blocked_environment`；不得使用替换来源、更新后的内容或原生流程续跑。 |
| 低风险局部 Bug | 私有方法空值遗漏，单模块可复现 | 一轮完成；有有效红绿回归；稳定轮跳过。 |
| 高风险数据变更 | 金额、SQL/Mapper 或事务变化 | 两轮完成；稳定轮原因明确；最终验证覆盖受影响模块。 |
| 假红灯 | 新测试因 Mock/编译错误失败 | 不改生产代码；先修测试或环境；不得把它记录为有效红灯。 |
| 紧急处理 | 用户明确要求紧急修复，且是低风险局部行为 | 可只保留目标行为测试和修改后验证；最终回执说明延期检查。 |
| 紧急高风险 | 用户要求紧急处理金额、迁移、事务/并发、权限、公共接口或发布变更 | 不得缩减；仍保留完整 TDD 证据和风险复查。 |
| 修复后测试失败 | 代码修复使旧断言失败 | 一次分类：真实回归/过期测试/环境；只有已授权的过期测试可同批更新。 |
| 跨服务恢复 | 两个服务、已发布契约，中断后继续 | 自动存在轻量状态；只在工作区、基线和范围匹配时恢复。 |
| 业务歧义 | 金额含义或公共 API 兼容性不明确 | 在开始改动前 `blocked_decision`；不得用默认假设继续。 |
| 过期验证 | 最后一次生产代码修改后只保留旧测试结果 | 不能 `complete`；验收项标为 `stale`，必须重新运行对应验证。 |
| 根因无进展 | 同一问题指纹修复后仍复现 | 停止自动修复并保留复现、调用链和假设证据；输出 `blocked_no_progress` 或 `needs_decision`。 |
| 脏工作区 | 存在与任务无关的用户 diff | 冻结其指纹；只修改本任务拥有的文件；修复回滚不得影响已有 diff。 |
| 待确认但验证通过 | 业务场景测试均通过，但有一个导出/兼容性规则需用户决定 | 用户回执标题为“需你确认”，不得写“已完成”；说明当前可用行为、已验证和未验证范围、实际影响及推荐方案。 |
| 连续复查无新增 | 同一任务再次检查，没有新发现且待决项未变化 | 只报告“无新增问题”和仍待确认项；不得重复完整流程、命令和文件清单。 |
| 意图评审去重 | `pdlc-v1` 已完成同一源码指纹的需求/设计评审 | 不再运行同类 `intent` reviewer；高风险时只补 fresh-context `blind` reviewer。 |
| 盲审独立性 | reviewer 继承了实现者完整对话或设计理由 | 必须标记 `independent=false`，不得宣称完成独立盲审。 |
| 审查失效 | reviewer 完成后生产源码变化 | 原结论标记 stale；closure 只复核原 finding，影响面扩大时最多再做一次风险审查。 |
| Batch 预检缺口 | 计划缺少验收、依赖接口或最终验收 | 一次性报告全部缺口并阻塞；不得开始 Batch 1 或自行补技术方案。 |
| Batch 重复派发 | 派发后连接中断，无法确认是否已创建执行任务 | 保留原 `dispatch_id` 并阻塞；不得再次创建同一 Batch。 |
| Batch 回执伪装 | batch/dispatch 不匹配，tree 与 verified tree 不一致，或证据陈旧 | 拒绝完成当前 Batch，不派发下一批。 |
| Batch 计划漂移 | 恢复时 `plan_revision` 或 fingerprint 变化 | 在同一 plan/run 状态上阻塞，不以新路径掩盖漂移。 |
| Batch 最终验收缺失 | 所有 Batch receipt 均通过，但计划级验收未知或陈旧 | 计划不能 complete；调度器不直接修代码。 |
| Batch 暂停恢复 | 用户 pause 后恢复同一计划 | pause 后不派发新 Batch；resume 重新校验计划、worktree、dispatch 和 receipt 后继续。 |
| 调度器越权 | Batch 执行失败或计划存在技术歧义 | 调度器不读业务代码、不 review、不自行设计或修复；形成阻塞证据。 |
| Worker 登记 | 派发 PDLC、reviewer、Batch、辅助分析或 evaluator | 宿主返回后立即登记稳定 ref、role、owner run 和 working；没有 ref 时手工交接，不 detached/fire-and-forget。 |
| 回执早于终态 | evaluator/worker 已返回结果，但宿主仍显示 Working | 继续查询/有界等待；无活动后才按 watchdog 中断；不把自然语言回执当宿主终态。 |
| 清场屏障 | 正常、异常、用户中断、no_progress 或验证失败退出 | 执行等价 `finally`，只处理本轮 worker；本轮 active worker 数为 0 后才允许完成。 |
| 历史孤儿 | UI 显示旧 Working worker，但没有 ref 或当前 API 不可见 | 报告能力边界并建议用户/UI 处理；Skill 不宣称发现、查询或清理成功。 |
| 独立前向测试 | 一次变更关联多个有限场景 | 一个 evaluator 在隔离临时工作区顺序执行；结束时等待其宿主终态并确认本轮 active worker 数为 0。 |
| 技术术语噪音 | 默认交付回执 | 说明结果、关键改动、验证覆盖、待处理，并保留用户可懂的交付轮数/问题数；不展示 `complete`、P0/P1/P2、lease、基线或命令。 |

通过标准：每个场景都有明确终态；单任务低风险不超过 1 个交付轮，高风险不超过 2 个；没有无证据或陈旧证据的完成结论；没有范围外自动修改；PDLC 可用时没有 native 阶段混入；Batch 没有重复派发、越权实现或跳过最终验收；evaluator 终态已确认且本轮 active worker 数为 0。任何场景不通过，都应先记录失败行为，再针对该行为修改 Skill，随后用新的独立运行复验。
