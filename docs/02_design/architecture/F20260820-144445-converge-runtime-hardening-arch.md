<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-144445 -->
<!-- 功能名称: converge-runtime-hardening -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260820-144445-converge-runtime-hardening-prd.md -->

# 架构设计：Converge 运行时闭环增强

## 1. 设计原则

- 保持三个用户 Skill，不新增编排层。
- 能用现有状态和宿主工具完成的，不新增 Python 抽象。
- 宿主差异放入 Batch 按需 reference；根 Skill 不加载。
- 模拟 E2E 与真实 Agent E2E 分开标记，禁止互相替代。

## 2. 组件变更

| 组件 | 变更 | 复用 |
|---|---|---|
| `install.sh` | 新增 `--doctor` 和 Suite 完整性版本展示 | 既有 target/source/mandatory files |
| `scripts/delivery_report.py` | 读取 Schema v5，复用 `delivery_next.validate_state`，输出 JSON/text | 既有 ledger、handoff、acceptance |
| `converge-batch/references/runtime-adapters.md` | Codex/Claude 的探测、派发、等待、恢复、receipt 契约 | 既有 Batch Protocol v1 |
| Batch 测试 harness | 用 fake host 验证两批接力、断线恢复和重复派发保护 | 既有 `batch_state.py` |
| activation reference | 提供关键词与可复制 AGENTS 片段 | frontmatter 和默认隐式调用 |

## 3. Doctor 与版本

`suite_status(runtime)` 检查三个入口：必须都是 symlink、Skill 名正确，并解析到 `converge` 根及其两个 `skills/` 子目录。输出：

```text
Codex: 0.8.0 (complete)
Claude Code: 0.8.0 (incomplete: missing converge-review, converge-batch)
```

`--doctor` 额外检查 Bash、Git、Python >=3.9、mandatory Suite 文件和执行引擎探测。PDLC 缺失不是失败，因为 native 是合法降级；入口残缺或必需依赖缺失退出非零。doctor 只读，不获取安装锁。

## 4. 确定性报告器

输入为 Schema v5 JSON。先调用现有结构校验，再生成：`outcome`、`goal`、`verification`、`completed_rounds`、`repaired_issues`、`pending_items`、`acceptance`、`next_action`。JSON 是机器接口，text 是稳定中文回执；不执行新检查或写状态。

待处理数 = 非 fresh pass 验收项数量 + 非空 `handoff.open_issues` 的一个汇总项。这样口径确定，且不猜测自然语言中有几个问题。

## 5. Batch 运行时适配

Batch Skill 根据宿主能力读取对应段落：

- Codex：创建新任务 → 保存 task/thread ref → 有界等待 → 读取结构化 receipt；连接中断先查询原 ref，不重派。
- Claude Code：使用可用的新上下文任务能力；无法获得稳定 ref/等待能力时输出 capsule 并暂停。
- 其他宿主：仅手工交接，不伪造自动调度。

运行时层不修改 Batch 状态规则。状态必须先写入 `dispatching`，成功取得 ref 后才写 `running`。

## 6. 验证设计

1. 安装器测试：完整/残缺/错源入口、doctor 依赖、版本展示。
2. 报告器测试：ready/decision/blocked、陈旧验收、轮数和问题数。
3. Batch fake-host E2E：两批接力、断线恢复、不确定派发阻塞。
4. 独立真实 Agent：隔离临时仓库执行一次两批计划，保存任务引用和回执结论。
5. 全量回归和三个 Skill 结构校验。

## 7. 风险与取舍

| 风险 | 处理 |
|---|---|
| 宿主工具名称变化 | reference 描述能力与当前映射，探测失败降级手工 capsule |
| 报告器复制状态校验 | 直接复用 `validate_state`，不复制 Schema |
| E2E 自称真实但只跑 fake | 结果显式标注 simulated/real |
| 自动触发仍受运行时控制 | 提升 frontmatter 与测试覆盖，不作 100% 承诺 |

## 8. 自审记录

- PRD P0/P1 覆盖：6/6。
- 无新增依赖、后台进程或用户 Skill。
- 安全边界保持：doctor/report 只读，dispatch 不确定即阻塞。
- 结论：通过。

---
作者：Jeff.Liu
状态：已评审

## Runner 输出传输的取舍

| 参考 | 采用 | 不采用 / 原因 | 行为验证 |
|---|---|---|---|
| [Filesystem Context](https://raw.githubusercontent.com/muratcankoylan/Agent-Skills-for-Context-Engineering/main/skills/filesystem-context/SKILL.md)；Skills.sh 对应条目检索不可访问 | 大输出文件化，返回紧凑引用，按需读取 | 不新增记忆服务、代理拓扑或自动删除策略；此次只修输出传输 | test_runner_output.py 大输出、分段、权限、有限预览 |
| [Python subprocess](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.communicate) | 并发排空两条管道，超时/取消独立清场 | 不用 communicate 累积全部执行日志 | 实际子进程大输出、真实超时、取消、既有孤儿进程组回归 |
| [Claude headless](https://code.claude.com/docs/en/headless) | 官方 stream-json 和最终 result 提取 | 不以提示约束模型必须预估全部日志大小 | Claude 命令断言及大 stderr 后最终结果回归 |

## 多模型协作的参考与取舍

| 参考与决定 | 采用 / 不采用 | 原因 | 行为测试 |
| --- | --- | --- | --- |
| [多代理模式原始 Skill 的显式交接](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/multi-agent-patterns/SKILL.md) | 采用与解析器一致的只读结果示例；不采用格式失败后的自动重试或结果改写 | 修复生产端提示的契约缺失，保留消费端严格校验与原始失败回执；Skills.sh 分类页不可访问，核对原始 Skill | `test_role_prompt_examples_round_trip_through_the_real_contract`、`test_file_line_ranges_from_the_failed_scout_remain_invalid` |
| [OpenAI 的代码编排与结构化输出](https://openai.github.io/openai-agents-python/multi_agent/) | 采用类型化、可验证结果 | controller 需要检查输出，而不是转述 agent 对话 | `test_role_result.py` |
| [Anthropic 的小样本评测与隐私观测](https://www.anthropic.com/engineering/multi-agent-research-system) | 采用固定、显式执行的 16 场景评测 | 先测合规、路由和用量，且报告不存 transcript | `test_multi_model_eval.py` |
| [Anthropic 的独立方向研究](https://www.anthropic.com/engineering/multi-agent-research-system) | 采用显式异质只读 fan-out | 对高风险任务降低同构偏差，不扩大写入并发 | `test_role_fanout.py` |
| peer swarm、成员互聊、自动扩容 | 不采用 | 编码任务依赖高；当前目标是可恢复的单写入者控制 | `test_role_flow.py`、`test_runner_lifecycle.py` |
| [Git rev-parse 路径输出](https://git-scm.com/docs/git-rev-parse) | 采用只移除行终止符的隔离 worktree 身份检查；不新增路径注册表 | 合法路径末尾空格不应改变单写入者隔离判定 | `test_writer_accepts_isolated_worktree_with_trailing_space_in_path` |
| [OpenAI 模型选择](https://developers.openai.com/api/docs/guides/model-selection)、[GPT-6 迁移](https://developers.openai.com/api/docs/guides/latest-model) | 采用 GPT-6 Luna/Sol 的实际可派发角色分层；不采用串行 Astra 画像 | 只有 runner 能切换模型；Sol high→medium 须经真实同模式任务对比，不把官方建议当作本仓质量结论 | `test_multi_model.py`、`test_multi_model_repo_eval.py` |
| [OpenAI GPT-6 Skill 指南](https://learn.chatgpt.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)、[skill-creator](https://developers.openai.com/codex/skills) | 采用短入口和按需加载；不新增 GPT-6 专属状态机 | 减少默认上下文与无效角色配置，同时保留既有授权、验证和有限退出边界 | `test_skill_contracts.py`、`test_multi_model.py` |
| [Claude Code 模型别名](https://code.claude.com/docs/en/model-config) | 采用现有 `haiku`/`sonnet`/`opus` 别名；不钉死具体版本 | 别名随宿主与提供方变化，保留显式 profile 与真实 smoke 门槛 | `test_multi_model.py`、`test_multi_model_smoke.py` |
| [多代理模式原始 Skill](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/multi-agent-patterns/SKILL.md)、[Superpowers 原始 Skill](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md) | 不采用每角色常驻或每阶段强制新代理 | 更强模型不构成增加代理的证据；保持单控制器与按需隔离 | `test_role_flow.py`、`test_role_dispatch.py` |
