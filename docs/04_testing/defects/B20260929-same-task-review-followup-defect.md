# 同一任务的后续审查停止闭环

作者：Jeff.Liu

证据：用户报告与 [Codex 对话](codex://threads/01a0ebd4-256e-7f22-b179-c1c7239ad999)。原任务已授权完成前后端功能闭环，随后用户多次要求检查当前实现；助手报告同范围问题后停止，等待用户再次催修，重复“审查→报告→催修→修复”。

## 根因

- 根控制器早已规定同会话授权持续有效，同范围审查 finding 应直接修复；因此这次不是缺少该条规则。
- 关键交互目录的审查闭环用例是单轮提示，提示本身已明确要求修复；没有覆盖“前一轮已授权实现，用户下一轮只说仔细审查/还有没有其他问题”的真实追问。
- `writes=after_review` 回执只检查整个场景曾经写过文件；前一轮实现写入可能掩盖审查轮没有修复。
- 原宿主 bridge 当时不能自动在同一线程回放多轮用户消息；后续新增了真实 app-server 同线程回放，结果见下方。历史缺口不能由单测或文字规则抹平。

## 修复

- 根 Skill 将同一任务后续审查明确路由回根控制器；独立 `converge-review` 仅用于没有活动同会话写入任务时的只读审查。
- 每轮可标记 `review_checkpoint`；`writes=after_review` 必须在该审查轮观察到实际工作区变化。
- 增加关键多轮场景：初始实现请求后，用户连续两轮只要求同一事项复核，后续轮不重新授权；预期不追问、同范围有 finding 时闭环修复并以新鲜验证结束。
- 本次按 SkillOpt 的分类记为 `EXECUTION_LAPSE`，采用手动离线候选优化与 held-out 评估边界；没有采集原始会话，也没有运行 SkillOpt 训练或声称模型行为改善。
- 后续配置增加默认关闭的每周证据复核；启用后只检查持久化 defect/eval 证据并报告候选，不自动训练或修改 Skill。
- 2026-09-30 复核发现多轮回执只校验最后一轮完成状态，中间复核轮只报告 finding 仍可通过；已要求每个复核节点都有完成状态与验证证据，并拒绝验证失败。无新问题的复核可以无写入通过，避免强制修改正确实现。
- 同次复核发现验证退出码未参与完成判定；已拒绝复核节点和最终完成轮最后一条验证命令失败的回执。该检查只是必要条件，不能替代独立 judge 或真实模型评测。

## 验证

- 新增回执回归先以“未按 review checkpoint 观察写入”失败，再通过实现。
- 定向交互目录、receipt 与 Skill 触发契约：70 项通过。
- 全量发布门禁曾完整通过一次。随后两次正式覆盖率入口均采集到 90.03%（门槛 90%）；包装门禁因既有 Claude CLI 启动用例返回非零而失败，其中一次失败断言为 `unavailable`/`failed` 状态不符。单独重跑该用例通过，但两次覆盖率包装运行都不能记作全量门禁通过。
- 真实宿主多轮行为保持 `uncovered`，需要 fresh-host receipt；不能用文档断言或确定性单测代替。
- 2026-09-30 新增回归先复现中间轮未完成、验证退出码失败仍被接受，再通过修复；定向交互检查 20 项通过。三轮场景的初始请求已经要求修复全部已知缺陷，因此它验证复核连续性，不单独证明复核发现新缺陷后能自动修复；后者仍需真实多轮带缺陷的宿主证据。
- 同日正式全量覆盖率达到 90.06%，但并行采集下再次复现 CLI 用例的 1 秒启动预算耗尽；成功启动及启动后精确确认用例改用已有成功用例的 5 秒预算，保留专门的短期限/超时行为测试和生产超时语义。修补前该次全量门禁仍算失败。
- 最终修补后定向测试 53 项通过；正式覆盖率入口 `python3 -m pytest scripts/test_coverage_gate.py --cov --cov-fail-under=90 -q` 通过，内部 `check.sh --full` 全量门禁通过，全量生产 Python 覆盖率 90.05%，没有调整统计范围或降低门槛。

## 2026-09-30 共享入口与真实回放

- 复用当前 review 状态、源码指纹和一次修复预算，当前各轴最新范围内缺陷返回 review-repair；旧 finding 经复核 pass 后不再触发，未分类及范围外问题不取得写入授权。相关 CLI 回归通过。普通桌面对话仍为引导模式，受管理入口与合成回放的控制器才能确定性拒绝失败结果。
- 新增评估器在第二轮复核前注入 strip 回归，独立固定 Python 判定器核对 None、普通、空及空白字符串；干净复核、已决策、新决策、持续外部失败均有回归。故障与线程身份变化记 uncovered，不重置修复预算。
- 真实 gpt-6.1-sol：修改前 Skill 对照 1/1 完成；候选第一次三样本批次有 2 个完成、1 个总时限耗尽。两个完成样本均在同一个 thread 完成两轮，复核直接修复注入缺陷，外部验证 exit 0、问号计数 0、额外修复轮 0。原始摘要保存于同目录证据文件。由于样本不齐且对照也成功，不宣称统计改善或正式候选晋升。
- SkillOpt adapter 已实现并通过官方四方法接口契约测试，但真实 SkillOpt 包未安装，未执行训练。默认拒绝 rollout；三项留出批次保证覆盖所有类别，不能用随机漏测代替验收。周度复核和自动晋升边界保持原约束。
- 补充一个独立 300 秒候选样本：初始实现完成，复核轮超时，保持 uncovered。没有继续重试或据此晋升候选。开发回放只获得 2 个完整候选成功样本，未达到三样本稳定性验收；正式模型改善仍未证明。
- 最终源码正式覆盖率入口通过，内部 check.sh --full 通过，全量生产 Python 90.17%（11801 statements、1160 missing），未调整范围或门槛。结果见 [full-gate](evidence/followup-closure-20260930/full-gate.txt)，宿主摘要见 [control](evidence/followup-closure-20260930/control.json)、[candidate batch](evidence/followup-closure-20260930/candidate-batch.json)、[candidate extra](evidence/followup-closure-20260930/candidate-extra.json)。

## 后续实际运行验收

- 用户要求继续后，官方 SkillOpt 0.2.0 固定 commit 79124b37e9a6371e13b753f8bcd7adb1e493ade1 已在临时 venv 实际安装，真实 EnvAdapter 和两个官方 CLI registry 均验证通过。首次 PyPI 下载超时，隔离依赖安装换用镜像成功；仓库依赖和默认关闭配置未改变。
- 回放原先没有冻结推理强度，继承本机 xhigh；现通过官方 turn/start 明确设置 medium，并在每轮摘要记录请求值。固定条件的三样本批次完成两个样本，第三个在总时限耗尽后未启动；保留该 uncovered 记录。补充独立同条件样本后，三个不同线程均完成两轮复核修复，外部 verifier exit=0、questions=0、automatic_repairs=0。该开发 smoke 不代表相对旧规则的统计改善，也不冒充正式 locked release。
- 真实 ReflACTTrainer 执行 epochs=1、steps=1、edit_budget=1、failure_only=true。选择和训练样本 hard=1，反思阶段没有失败组和可用补丁，skip=1，初始 Skill 与 best_skill 字节一致：按停止规则保留原 Skill，不为产生候选而强行修改。官方摘要仍写 skillopt-0.1.0，但实际安装 metadata 为 0.2.0；原始摘要未重写。
- 内部训练 test 关闭，由独立冻结回放使用真实已安装 adapter 检查全部三类留出场景：clean-review 两轮均无写入、无追问；new-decision 第二轮一次提问且无写入；no-progress 两轮 verifier 都失败，消费一次修复后 blocked。三项 hard 均为 1。
- 修补优化评分：普通场景若控制器催修后才通过，hard=0，并保存独立 result.json 摘要；不能让控制器替模型取得合格。红灯已复现，相关回归通过。目标模型成本仍未计入官方训练器 token tracker，零优化器调用不能说成整个试验零成本。
- 本轮前两次全量门禁失败都保留：第一次 Python 矩阵测试触发 3 秒等待，单独核实通过；第二次 Claude 普通失败分支的 1 秒启动预算使其在 inventory 阶段返回 unavailable，而未到断言的 exit=7 分支。进一步核实后，普通 exit=7 用例改为在外部调用边界确定返回该错误码，避免把库存探测超时混入已启动错误分支；同时断言只调用一次。矩阵假工具用一次 builtin printf 记录整行、去除锁和额外 env/touch 子进程，保持 3 秒限制与顺序/失败断言。专门短期限和生产 timeout 未改。最终门禁另行完整重跑。
- 完整模型结果、实际包版本、训练摘要、留出验证、预算、冻结快照和失败日志见 [后续运行证据](evidence/followup-validation-20260930/manifest.json)。默认不训练、周度只读复核、候选不自动晋升的边界保持有效。

- 同轮又以确定性红灯复现 Codex 创建确认的退出竞态：第一次读取 JSONL 尚无确认，随后 child poll 观察到退出时，确认已写入但旧路径直接返回 indeterminate。共享 dispatch_codex 现在先观察退出、再读取确认事件；新回归及 34 项派发检查通过。该修复不调整生产时限，也不允许重试已启动但未确认的任务。

- 最终完整门禁通过：python3 -m pytest scripts/test_coverage_gate.py --cov --cov-fail-under=90 -q，内部 check.sh --full 全部通过；全量生产 Python 覆盖率 90.16%（11805 statements、1162 missing），范围和 90% 门槛不变。定向共享入口/宿主/回放/适配器 185 项通过，派发 34 项通过，矩阵测试原 3 秒约束通过。完整结果见 [最终门禁](evidence/followup-validation-20260930/full-gate-passed.txt)。实际运行链路完成，本轮没有新的 SkillOpt 补丁或正式候选晋升。
