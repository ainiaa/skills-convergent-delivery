# Converge 轻量核心实施计划

## 目标

让普通的单轮任务保持直接、无状态、无快照、无 worker 生命周期；仍要求对最终源码运行真实验证。只有跨轮恢复、自治、批量或多模型任务才加载各自的控制面。保留 Plan v6 的计划闭环，以及既有 work item 的精确恢复语义。

本轮不复制 PDLC，也不合并 batch/autonomy/work-item 的状态，更不新增后台循环、代理、发布或依赖。

## 已决设计

| ID | 决定 | 原因 |
| --- | --- | --- |
| D1 | inline 路径只负责路由和直接执行；不创建状态、lease 或 controller snapshot。 | 简单任务无需恢复和隔离成本。 |
| D2 | `work_item` 继续作为跨轮任务的唯一可恢复状态；它不承载自治或批量状态机。 | 三者的租约、停止和所有权语义不同。 |
| D3 | extension 只在相应入口显式、延迟加载；核心安装和测试不依赖 extension 模块。 | 把可选能力从普通任务的导入与故障面移开。 |
| D4 | 完成只能来自绑定最终源码的 observed evidence receipt。 | 不能把模型报告当作完成。 |

## 参考机制记录

| 能力 | 采用 | 不采用 | 行为验证 |
| --- | --- | --- | --- |
| 轻量顺序路径 | PDLC 的 Skill + 明确命令 + 有限停止模型。 | PDLC 的 Markdown 状态代替 Converge 的证据/恢复契约。 | inline 导入/落盘边界和真实验证。 |
| 恢复与控制面 | 现有 work item、lease、atomic state 的精确恢复边界。 | 把所有任务都升级为自治状态机。 | 唯一匹配事项才可续跑。 |
| 计划闭环 | Plan Contract v6 的单结果任务和 closure receipt。 | 子计划或每任务额外代理。 | 计划校验、定向测试与最终全量检查。 |

## 顺序任务

### T1 — 直接路由不加载重控制面

- 先写失败测试：inline/normal 路由不导入 snapshot、lease 或 runner 生命周期模块，且不创建 managed state；planned 路径仍保留 Plan v6 校验入口。
- 最小实现：将 `delivery_next` 的扩展依赖移至只有对应状态校验会调用的局部导入，不改变冻结路由和现有外部 CLI。
- 验收：普通任务可直接到真实 verifier；重控制面不会因导入副作用进入该路径。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_delivery_next scripts.test_task_profile`。

### T2 — 跨轮 work item 保持为独立的最小状态

- 先写失败测试：恢复的唯一事项仍锁定 workspace、baseline、acceptance 与参考 binding；它的常规验证不需要自治/batch/multimodel 模块。
- 最小实现：把 work-item 核心与可选执行控制的连接改为窄、显式边界；不迁移既有事项 schema，也不新建 ledger。
- 验收：需要恢复的任务仍可精确恢复、重复失败仍有限停止；简单恢复路径不装载可选运行时。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_work_item`。

### T3 — 快照与引擎仅服务扩展能力

- 先写失败测试：默认 core snapshot 只包含核心文件；请求 autonomy/multimodel 扩展时才包含相应文件，已有快照/runner 兼容性不回退。
- 最小实现：沿现有 extension registry 收紧默认入口与导入边界；保持自治、批量和多模型的原有租约/清场语义。
- 验收：核心可独立校验；重模式仍通过其既有生命周期测试。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest scripts.test_controller_snapshot scripts.test_delivery_engine`。

### T4 — 闭环与删减

- 只删除前三项证明不再由任何路径使用的重复 glue；不做目录大迁移。
- 验收：每种路由只加载其需要的能力，所有声明的验证、90% 覆盖率与全量检查通过。
- 验证：`bash scripts/check.sh --full` 与 `git diff --check`。

## 停止条件

若某项需要改变公共 CLI、状态兼容性、权限或发布边界，停止并单独提出该决定；不能用“轻量化”绕过真实 evidence、输入校验或自治清场。
