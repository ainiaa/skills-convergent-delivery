# 原生验收工具缺口误停后续实现

用户截图报告：原生验收工具超时后停止了仍未完成的实现，需用户再次催促才继续 B02b。截图中的功能名、模型选择属于故障上下文，不扩大本次修复范围。

根因：现有 `plan_execution.py` 只区分 Plan 的图谱工具缺口；native preflight 虽返回 uncovered，执行契约没有明确继续独立可验证工作的边界。缺证据不能完成，被扩大解释为不能继续实现。

冻结行为：范围、验收和写入授权已确定，下一源码任务有独立可执行验证时，工具不可用/超时保留 uncovered 并继续实现。未经授权、测试失败、权限/业务错误、无法独立验证或受管 block 仍停止。验收缺口不能签发 complete，工具不自动重试。

## 参考机制取舍

先检索 Skills.sh 的 testing 分类及 HumanLayer control-loop 条目，再核对原始来源；安装量只用于发现。

| 来源 | 采用 | 不采用及原因 | 行为验证 |
| --- | --- | --- | --- |
| [OpenAI skill-creator](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md)，本机当前版本 | 简短入口规则、细节放 reference；保留用户授权边界 | 不增加状态和通用降级框架，局部缺陷不需要新协议 | helper CLI 使用真实 preflight，核对 execute、uncovered 与无写入副作用 |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 区分观测与控制决定，复用可独立运行的控制命令 | 不引入定时工作流、记忆文件或额外代理，本次是现有执行规则修复 | 工具缺口与真实验收失败返回不同下一动作 |
| [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | 完成声明绑定新鲜验证证据 | 不把完成门禁延伸为整段实现禁止，独立源码检查仍可执行 | 既有 tdd_impact_guard 的 uncovered graph/coverage 测试保持通过 |

复用既有 helper，无新状态、角色或循环。控制器仍拥有任务冻结、独立验证判断、写入和终态责任；helper 只选一个 implementation 动作，不完成任务、不修改受管状态、不撤销 stop/block。普通 ready 路径仍为原动作，简单 inline 不创建额外文件或 worker。工具失败不重试；用户停止、契约阻塞和预算规则保持原门禁。

`scripts/test_plan_execution.py` 的新增测试先红后绿，覆盖 timeout/unavailable、有/无授权、真实缺失 index/coverage、ready、测试失败与混合权限错误。测试通过公共 decide/CLI 验证可观察结果，不以文档关键词放行。真实宿主模型是否遵循新规则尚未独立回放，仍为 uncovered。

本轮验证：10 项 helper 测试与官方 Skill 校验通过；deterministic eval preflight 为 ready（模型行为和宿主 evaluator lifecycle 仍 uncovered）。全仓 `scripts/check.sh` 未通过：现有 EvalKernel 夹具选择 HEAD/HEAD^，当前合并提交二者 tree 均为 `5bbdfa5e5e53ee3b97228bfe357816603b183b22`，触发 distinct frozen Git trees 拒绝；用 HEAD 中未改动的测试源码复现相同失败。完整覆盖率命令 `python3 -m pytest scripts/test_coverage_gate.py --cov --cov-fail-under=90` 未通过，测得 89.13%，本次 helper 为 100%；完整 gate 另有 trusted snapshot 执行测试失败，未独立归因。未修改判定器、统计范围或门槛取得放行，本次不得报告全仓验收完成。
