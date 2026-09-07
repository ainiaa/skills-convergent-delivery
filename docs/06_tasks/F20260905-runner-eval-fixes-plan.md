# Runner 与评测遗漏问题修复计划

作者：Jeff.Liu

基线：`764e0a9fedbf5e52afc0016a26629ef0ee57d8db`；开始时工作区干净。执行：Plan v6，native-v1，same_session 顺序。

## 范围与验收

1. T1：先复现主进程退出、后台子进程重定向输出后仍写文件；在共享执行器修复本次进程组清理，覆盖正常退出、非零退出和清理异常。保持输出解析、超时、权限及回执结构。
2. T2：先复现报告任务缺失、重复、集合不一致和摘要矛盾；复用结果与摘要字段校验，保留完整报告与历史耗时缺失的兼容处理。
3. T3：说明 single/multi 测量单写入及追加审查的执行情况，不能证明审查提高修复成功率；运行全量检查和计划审计。

不新增代理、依赖、执行循环或状态协议。普通计划矩阵分层属于待验证设计，本轮不改变。没有真实宿主独立 evaluator 回执，locked differential 与真实模型收益仍为 uncovered；本地回归不能替代这些证据。

## 第三方机制取舍

| 来源 | 采用 / 不采用及原因 | 对应验证 |
| --- | --- | --- |
| [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | 采用新鲜行为证据；不以 exit 0 单独推断全部副作用停止 | T1 退出后写入探针、异常清理回归 |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) | 采用同题结果完整比较；不把多一次审查当作修复收益 | T2 任务集合与摘要校验，T3 用途说明 |
| [HumanLayer design-control-loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 复用现有执行器和摘要；不新建清理服务或评测循环 | 现有 runner、lifecycle、评测回归 |
| [Harness Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/harness-engineering/SKILL.md) | 修改前已创建仓库外只读控制器快照；不修改旧判定器自证 | 对照探针保留、最终范围审计 |

## 执行记录

- 计划校验通过：T1 → T2 → T3，sequential，不要求 commit 授权。
- T1：两个 runner 的正常/非零退出探针及清理异常共 6 个子场景先失败；修复后 runner 25 项测试通过，lifecycle/runtime 集成检查通过。
- T2：缺项、重复、任务集合不一致、空结果、摘要矛盾、状态矛盾、模式矛盾和计划/执行混合共 9 个子场景先失败；修复后完整评测测试通过，保留失败报告与旧报告缺少耗时的兼容行为。
- T3：已补评测用途和进程组清理能力边界；最终全量检查与计划审计结果写入仓库外执行证据。
- 控制器快照描述：`/tmp/converge-review-fixes-snapshot.json`。
- 机器计划固定为任务定义，执行证据保存在仓库外，不将 pending 改作完成状态。
- 最终审计输入：`/tmp/converge-review-fixes-audit.json`；结果：`/tmp/converge-review-fixes-audit-result.json`。
