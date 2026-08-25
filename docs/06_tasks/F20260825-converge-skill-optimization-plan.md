# Converge Skill 最终优化计划

## 目标

在不增加第二状态、后台循环或新入口 Skill 的前提下，降低简单任务的激活与控制开销，保持复杂任务的有限证据闭环，并把无法由仓库自行完成的宿主集成明确阻塞。

## 冻结边界

- 可修改：根/子 Skill 说明、现有 references、评测与契约脚本及其测试、参考矩阵。
- 不修改：Git 历史、外部宿主、全局配置、发布或安装行为。
- 已决：风险决定 review/verification，不决定执行拓扑；没有真实宿主 bridge 时，不允许自动 worker 完成。
- 外部阻塞：真实 Codex/Claude bridge 必须由宿主提供 task query/tree observation API；本仓库只定义并验证接入契约，不能伪造该实现。

## 执行切片

1. **入口渐进披露**
   - Outcome：低风险 inline 任务不加载持久状态、worker、watchdog 或报告细节。
   - Paths：`SKILL.md`、`references/*.md`、对应契约测试。
   - Verify：Skill validator、`test_skill_contracts.py`。

2. **简单确定性 fast path**
   - Outcome：仅单个普通文档文件的局部变更在已有确定性检查下跳过 Provider/完整画像开销，但仍保留授权范围、Git diff 与 writer lease。
   - Paths：`SKILL.md`、`references/task-routing.md`、压力场景与契约测试。
   - Verify：路由/Skill 契约测试；压力场景明确不适用于业务逻辑、风险或未知验证。

3. **宿主与触发评测边界**
   - Outcome：没有 bridge 时生成明确 blocked/manual handoff；真实 selector 和 bridge 的 release 验收输入、输出与失败语义可执行且不伪称已集成。
   - Paths：`references/execution-control.md`、`skills/converge-batch/references/runtime-adapters.md`、`references/evaluation-scenarios.md`、测试。
   - Verify：runtime/trigger/状态测试。

4. **行为基准与参考收敛**
   - Outcome：定义固定场景与所需指标，使 token、工具调用、用户阻塞和完成率可以对照；记录热门 Skill 的采用与不采用。
   - Paths：`references/evaluation-scenarios.md`、`docs/02_design/architecture/*.md`。
   - Verify：`converge-eval` 压力场景；真实 host/selector 可用前报告 `uncovered`，不将单测称为效果证明。

## 顺序与停止条件

按 1 → 2 → 3 → 4 顺序执行。每个切片先更新行为测试或压力场景，再改规则；任一规则无法由现有 host 验证时停在 `blocked_environment`，不创建模拟 bridge。结束时运行 `bash scripts/check.sh`，并用 fresh evaluator 复核 fast path、风险路由与 bridge 缺失三个场景。

## 实施记录（2026-08-25）

- 已完成 1：入口缩短至 11,163 UTF-8 bytes；复杂细节继续按需进入 references。
- 已完成 2：`fast_path.py` 仅为一个普通文档文件签发 receipt，并把实际成功的检查绑定到 Source Receipt；`SKILL.md`、风险/运行时路径、多文件和非空风险声明被确定性拒绝。
- 已完成 3：自动 worker 在缺少 host-observed bridge 时维持 blocked/manual；`trigger_eval.py` 的本地 selector 结果新增 `release_status=uncovered`，`--release` 固定阻断，避免模拟 selector 形成发布放行。
- 已完成 4：场景表记录 token、工具调用、用户阻塞、完成率；外部参考采用/不采用记录已更新。
- 验证：全套 `bash scripts/check.sh` 通过；独立前向评估发现的 fast-path 与 selector 两个可绕过点已补为上述回归测试。真实 host selector/bridge 仍是外部 `blocked_environment`，本仓库不伪造实现。
