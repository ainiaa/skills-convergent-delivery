# Converge 自进化参考备忘

> 状态：研究保留，当前不启用  
> 复核日期：2026-08-24

本文只保存未来可能使用的机制与边界，不属于当前 Converge 运行协议。任何现有 Skill、helper、状态机或 hook 都不得因为本文自动学习、自动修改仓库或扩大写权。

## 目标与非目标

未来若启用，自进化只解决一个问题：把重复出现、已有客观证据的交付失败，受控地转成更好的 Skill 规则、helper 或 reference，并证明它能迁移到未见场景。

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

安装量只用于发现，不作为采用依据。采用前仍需检查原始 `SKILL.md`、脚本、测试和宿主能力。

## 如果未来实现，最小协议

只允许显式维护任务触发，不设置自动 hook：

```text
verified defect / repeated correction
  → proposal: DISCARD | IMPROVE | MERGE | CREATE | SUPERSEDE
  → bind source defect, trajectories, affected surfaces, hypothesis
  → human authorization
  → freeze old Controller Snapshot and held-out evaluator
  → change one hypothesis on the smallest skill-folder surface
  → public regression + isolated held-out transfer tests
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

## 启动条件

只有同时满足以下条件才重新评估实现：

- evaluation locked surface、worker provenance、held-out 隔离已经稳定；
- evaluation catalog 有明确维护责任和覆盖检查；
- 已积累至少三组可归类的重复失败或改进轨迹；
- 用户明确授权构建受控演进能力；
- 能证明新增机制比人工 defect → test → fix 流程减少真实成本。

在此之前，继续使用人工授权的 defect-driven hardening；本文不进入 Controller Snapshot，也不被任何 Skill 自动读取。
