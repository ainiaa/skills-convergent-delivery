# 外部参考驱动的最小改进方案

日期：2026-10-16。作者：Jeff.Liu。

## 目标与边界

减少不必要提问，使中断后的诊断可操作，并验证控制器的授权、停止、恢复和完成边界。沿用现有状态、租约、Plan v6、宿主桥接与评测 runner；同会话顺序执行，不新增常驻进程、代理层、状态库、依赖或发布动作。保留开始时已有的七个未提交文件改动。

## 参考、采用与排除

先经 [Skills.sh](https://www.skills.sh/) 发现参考，再核对以下原始内容；排行仅用于发现。

| 参考 | 采用 | 已有或不采用及原因 | 行为验证 |
| --- | --- | --- | --- |
| [Grilling](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md) | 独立且前提已决的问题同轮提出；事实自行查；依赖未决答案的问题后置 | 不遍历与验收无关的所有设计分支；不默认派代理；已决事项复用已有 Plan decisions | replay 验证讨论阶段无写入、授权后实际修复；问题独立性、依赖与已决复用的语义不由标点判定 |
| [grill-with-docs](https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md) / [to-spec](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-spec/SKILL.md) | 用已有术语和已决事项综合计划 | 不默认创建 glossary/ADR；当前已有先查事实和已决记录，不再造访谈或决策状态机 | 授权前后写入边界及普通计划回归 |
| [to-tickets](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-tickets/SKILL.md) | 独立可验收切片、真实阻塞边 | Plan v6 已有单 outcome、依赖 wave、wide_refactor 和 integration，不改 schema；不默认发布 issue | 复用 plan_check 的切片、依赖与审计测试 |
| [GSD Core 恢复指南](https://github.com/open-gsd/gsd-core/blob/next/docs/how-to/recover-and-troubleshoot.md) / [契约测试](https://github.com/open-gsd/gsd-core/blob/next/tests/check-contract-drift.test.cjs) | 可行动的恢复结果、会失败的链路用例 | 不复制其 Markdown 状态和默认 fresh-agent 编排；本仓结构化记录和完成门禁已存在 | doctor 只读集成测试；复用并补齐已有审查→修复→复审→完成轨迹 |
| [Ralph TUI](https://github.com/subsy/ralph-tui) / [持久化测试](https://github.com/subsy/ralph-tui/blob/main/src/session/persistence.test.ts) | 状态、恢复、日志从现有真源派生 | 复用 doctor，不新增 TUI、远程服务、resume 自动抢租约或独立日志真源 | 有效、阻塞、损坏、终态诊断；读取前后字节一致 |
| [HumanLayer control loop](https://github.com/humanlayer/skills/blob/main/plugins/design-control-loop/skills/design-control-loop/SKILL.md) | 本地可独立验证、客观测量驱动下一步 | 既有 next-action、有限预算和停止条件保留；不新增定时循环或跨 run 自学习文件 | 现有 runtime/autonomy 轨迹与审查闭环回归 |

## 当前实施范围

1. 澄清规则复用代码、测试和已决事项，独立问题可同轮提出，依赖问题后置。交互回放仅判定可观察的写入边界、冻结验证、同任务身份与有限修复；问号数量只记录，不参与放行，不声称证明需求语义。
2. 任务 doctor 从已有状态派生只读恢复指引，复用共享下一动作与租约校验，不自动接管、续跑或写入状态。覆盖有效、阻塞、损坏、完成后待宿主同步，以及本地和冻结控制器命令路径。
3. 保留评审缺陷→修复→当前源码复审→完成轨迹，拒绝未关闭缺陷、旧源码通过记录、重复扣除首次集成预算及提前完成。
4. 保留通用验证器的缺失工具、超时、二进制输出和非法 argv 处理，以及 Git 探测超时的显式阻塞和任务标识保留。

原工程题库及其专用 JDK/SQL/分页测试、安装必需项和使用说明已删除；该题库未隔离控制器的贡献，维护成本不符合通用 Skill 目标。原一次性执行计划随范围收缩删除，不作为恢复或执行输入。默认轻量 runner smoke 保留，不新增替代题库、判定器或框架集成。

## 验收边界

本轮先修改回归，旧实现因问号数量误拒合法过程的四项失败，再简化判定。保留提前写入拒绝、失败验证、有限修复和宿主身份变化回归。最终运行完整检查和全量生产 Python 覆盖率门禁，范围与 90% 阈值保持不变；验收期间冻结源码。

真实模型的澄清语义、宿主完整生命周期和成本收益仍未覆盖；确定性测试与预检不能替代这些证据。不安装依赖、不提交、推送或发布。

## 精简后的验证结果

- 定向交互、评测器和安装回归 84 项通过；补充通用超时用例后，评测器 20 项通过。
- 首轮完整 gate 被本次编辑持有的真实 workspace lease 拦住三个计划集成测试，不计作验收。源码编辑结束并正常释放租约后重跑，未修改互斥保护或测试绕过该边界。
- `python3 -m pytest scripts/test_coverage_gate.py --cov --cov-fail-under=90` 退出 0，140.89 秒；内含 `bash scripts/check.sh --full`，全量生产 Python 覆盖率 **90.42%**，统计范围和 90% 门槛未变。
- 最终 gate 前后 Source Receipt 一致：`10a9c0dc0017c5fcf436f43d530f4e775b6999e55f852b8c72134440f9979184`。本节是验收后的结果记录。
- 修改前冻结控制器的 deterministic preflight 返回 ready，模型行为与宿主生命周期仍 uncovered；`git diff --check` 通过。

## 精简后的同范围复核

未发现已删除题库、任务 ID、安装资源或旧一次性计划的运行时残留引用。通用工具异常、预算耗尽、宿主身份变化、恢复只读性及评审完成门禁回归继续保留；历史证据文件保留当时的观察，不将旧问号计数当作当前语义证明。

补齐回放的只读停止边界：违规写入后立即返回 fail 并关闭会话，不再继续后续用户轮次或执行自动修复；clean-review 也拒绝额外文件写入。先以五类场景的额外写入构造失败回归，再复用现有分支修复；合并原本重复的讨论写入测试，没有新增配置、状态或判定器。交互与通用评测器定向 37 项通过。

本轮最终验收：相关调用方回归 30 项通过；完整 coverage gate 退出 0，140.07 秒，生产 Python 覆盖率 **90.42%**，统计范围及 90% 门槛未变。验收前后 Source Receipt 一致（`ead1187963d81cc00479bd5933ba602ed111eca07fc85a220719a17ad09fa8e6`），本段为其后的报告记录。修改前冻结控制器预检 ready，模型行为与宿主生命周期仍 uncovered；没有提交、推送或发布。

## 全部改动的通用控制器复核

评审记录消费、当前源码完成门禁、有限预算、只读诊断与按需澄清均属于控制器职责；实现继续复用现有状态、校验器和下一动作，无技术栈题库、额外代理或持久状态机制。两个仍会逃逸的损坏输入已在共享边界修复：execution_control 的非对象值在升级前拒绝；快照三个路径的类型错误由 validator 转为 ValueError。CLI 对三类损坏控制对象及三个 null 快照路径返回绑定任务的 block，doctor 保持字节不变并返回 repair-state。两项 CLI 回归先失败后通过；扩展 doctor 测试时出现的一次夹具参数错误已修正，不计作验证证据。最终状态、快照和下一步模块定向 225 项通过。

本轮完整 coverage gate 退出 0，135.08 秒，生产 Python 覆盖率 **90.44%**，范围和 90% 阈值未变。验收前后 Source Receipt 一致（`3d5de26cdfc145b30165ccc5d555946a84d0a1f09215c6c2f666c597d4f9a682`），本段为验收后的报告记录。修改前冻结控制器预检 ready，模型行为与宿主生命周期仍 uncovered；`git diff --check` 通过。未提交、推送或发布。

继续核对类型校验顺序，补齐扩展名/冻结文件列表在去重前检查元素类型、协议和状态版本拒绝非整数，以及旧 profile 的无效类型归类。已有支持的快照与安全释放路径不变；两项新回归先因 TypeError 失败，调整共享校验顺序后相关 226 项通过。没有增加自动恢复、重试或新协议。

本轮首个全量 gate 因既有 `test_timeout_cleans_up_descendants_before_returning` 的启动输出断言失败：300ms 超时前未观察到 started，单项复验通过。该测试不在当前修改范围，未改断言或时限；负载敏感性作为范围外测试风险保留。源码不变的最终完整 gate 退出 0，160.18 秒，生产 Python 覆盖率 **90.44%**，范围及门槛未变；两次 gate 前后 Source Receipt 均一致（`aafb929d721ee0f218964fd78234cdc7c5410d654d83453f3c44dc53133a56f4`）。冻结控制器预检 ready，模型行为与宿主生命周期仍 uncovered。本段是验收后的报告记录。

## 超时清场测试的最终方案

父/子进程先通过 ready 握手，再交给现有执行器测试真实 300ms 超时。子进程持有输出管道并等待 release，未清理后代就无法正常排空。保留 124、精确 stdout 指纹、父进程已退出与无 late.txt 的断言；启动替身核对 cwd、两条管道、独立 session、env 和位置参数。断言全部先于夹具兜底执行。

夹具以独立 SIGKILL 清理自己创建的进程组，最多等待 1 秒，再分别关闭两条管道；每一步放入 finally，前一步失败仍继续后续清理。只有进程组已消失被忽略；其他清理错误如实失败并通过异常链保留原异常。该处理不依赖被测 helper，也不使用 Popen 上下文的无限等待。握手有独立 5 秒预算，父进程提前退出会立即结束等待。

本轮将重复的原异常测试合并为一组失败注入矩阵；新增异常注入先复现信号错误跳过 wait/close 的问题，再修复顺序。没有新增共享夹具、运行时接口、重试或依赖，生产逻辑未变。

| 路径 | 实际验证 |
| --- | --- |
| 500ms 慢启动 | 旧测试确定性失败，新握手通过 |
| 启动退出、父/子进程一直未 ready | 按预期报错；父进程回收，两条管道关闭 |
| 错误启动参数、验收断言失败 | 必须拒绝；独立兜底后父进程回收、管道关闭 |
| 被测 helper 只杀父进程 | 真实管道排空失败，夹具独立清场 |
| 正常清理、进程组已消失 | 原异常保留，wait(timeout=1) 与两条 close 均执行 |
| 信号失败、wait 超时、stdout 或 stderr close 失败 | 后续清理步骤均执行；清理错误及原异常链保留 |

证据模块 39 项通过。修复后再次逐个核对上述退出路径，未留已确认的同范围缺陷；最终验收在源码冻结后运行全量检查和 90% 覆盖率 gate，不靠重复采样放行。

最终验收：本轮首次完整 coverage gate 退出 0，137.12 秒，生产 Python 覆盖率 **90.44%**，统计范围及 90% 门槛不变。验收前后 Source Receipt 一致（`9f0219e4f80b63f65d9f132850395d57d5da384581518335593e186653646a46`）；本段是其后的结果记录。冻结控制器确定性预检 ready，模型行为及宿主生命周期未运行；`git diff --check` 通过。未提交、推送或发布。
