# 原生计划显示修复计划

作者：Jeff.Liu

按 T1 → T2 → T3 同会话顺序执行。已有未提交修改纳入基线，不重做上一轮修复。

## T1

冻结原生面板与文字降级的修复范围及验收。

验证：`python3 skills/converge-plan/scripts/plan_check.py validate --input -`。

## T2

有原生工具必须同步并核实回执，缺少或失败时明确降级；文字轨迹不冒充原生显示。

验证：`PYTHONPATH=scripts python3 -m unittest test_step_trace_eval test_skill_contracts test_delivery_progress`。

## T3

文档和 changelog 与能力边界一致且受影响检查通过。

验证：`CONVERGE_QUICK_VALIDATE=/tmp/converge-official-quick-validate.py bash scripts/check.sh --full`。

## 取舍与证据

采用 skill-creator 的最小决策规则和既有宿主投影；采用 Anthropic 事件观测思路，但必须另核对原生工具调用结果。仅有文字可见、计划文件或状态投影均不代表界面已同步。不新增工具代理、显示状态机或伪造原生面板。现有宿主工具缺失是能力限制，先明确降级，不阻塞已授权修复。

离线验收覆盖：有工具未调用、成功回执、失败/未知回执、能力缺失未披露、明确文字降级及无显示证据。原生 UI 实际渲染和独立多样本稳定性仍无宿主证据，不用 fixture 放行。旧判定器保留在候选仓库外，既有 locked judge/catalog 不变。
