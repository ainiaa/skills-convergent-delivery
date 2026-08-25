# Converge 0.20 控制面一次性硬化记录

本轮只处理已复现且会影响完成可信度或子任务效率的控制面缺口；不增加后台守护进程、持久队列、第二状态库或自动自改循环。

| 问题 / 参考能力 | 采用的最小机制 | 行为验收 | 未采用与原因 |
|---|---|---|---|
| 宿主能力不能靠自由布尔值放行 | `negotiate` 与 `bind` 仅产出 `controller_attested`；只有 `bind_observed` 可接受 query id、时间、profile 与 canonical capabilities 的完整原始桥接观察；Schema v4 绑定原始 observation 和 fingerprint；Codex profile 静态禁止 activity/process/resume | `scripts/test_runtime_adapter.py`：全 true Codex 仍 terminal-only；generic bind 无法构造 host-observed | 不引入签名服务或 runtime daemon：本地同权进程不能获得密码学来源保证，冻结 controller + 原始桥接回执已关闭正常路径误放行 |
| 超时建议未落到宿主调用 | watchdog 返回受 `run_contract.py` 校验的 `query|wait|interrupt|block`，始终绑定 task/worker；不支持 wait 时退回 query | `scripts/test_runtime_adapter.py`：terminal-only 只 wait/query，observed 才 interrupt | 不另建 scheduler：控制器已有唯一派发权和 worker registry |
| 子任务被中断前丢失上下文 | observed soft probe 前固化已有 milestone/source/verification 为 partial handoff；它不代表完成，也不触发重派 | `references/execution-control.md` 与 runtime action 测试：无活动证据前不 interrupt | 不增加 worker partial-state 字段：现有 `progress`/handoff 已是同一状态真源，新增可写日志会制造双重事实 |
| 计划将 TBD 误当已决 | Plan v5 拒绝标准占位 resolution | `skills/converge-plan/scripts/test_plan_check.py` | 不限制真实技术决策自由文本，只拒绝无决策标记 |
| trigger eval 只指纹 argv | selector descriptor 绑定 argv 与实际 artifact 内容 sha256 | `scripts/test_trigger_evals.py`：修改 selector 文件会改变 fingerprint | 不加入多后端 eval harness，当前真实执行+F1 已覆盖目标 |
| 评测证据可在 candidate tree 内伪造、registry 顺序敏感 | Sample v4 强制候选仓库外的 absolute evaluator-attested artifact；registry 比较使用集合 | `skills/converge-eval/scripts/test_eval_kernel.py` | 不宣称 evidence 是 host-signed：当前宿主没有可验证的 evaluator-output artifact API |
| 老快照继续执行旧安全规则 | Controller Protocol v12 阻止旧快照执行，唯一兼容动作是释放自身 lease | `scripts/test_controller_snapshot.py` | 不热修已冻结脚本：会破坏快照可审计性 |
| 简单任务加载无关控制细节 | 根入口仅在非 inline/worker/recovery 路径读取 execution-control | `scripts/test_skill_contracts.py` | 不拆出新入口 skill，现有渐进披露已足够 |

外部取舍：Agent Skills 的 discovery → activation → execution 三段渐进披露支持按需读取 references；SkillHone 的“整 skill 文件夹、隔离评测、held-out gate”支持本轮将脚本、契约和文档作为同一候选改动，但其 Forgejo/持续优化服务超出当前任务。参考：[Agent Skills](https://github.com/agentskills/agentskills/blob/main/docs/home.mdx)、[SkillHone](https://github.com/Tencent/SkillHone)。
