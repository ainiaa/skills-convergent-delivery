<!-- PDLC-TRACE -->
<!-- 功能ID: B20260821-082738 -->
<!-- 功能名称: converge-known-findings-closure -->
<!-- 阶段: review -->
<!-- 前置文档: docs/06_tasks/F20260821-converge-known-findings-closure-plan.json -->
<!-- 创建时间: 2026-08-21T08:30:50+08:00 -->

# Converge 已知问题闭环缺陷记录

## 根因分析

1. Snapshot 只移除了根目录和文件写权限，遗漏中间目录；冻结 helper 还会先导入同目录模块再验证状态中的 Snapshot。
2. Provider resolver 动态扫描 manifest，Snapshot 却维护固定五项清单，形成两套 registry 真源。
3. 通用 TDD 首次发现校验了必需词和危险词，Binding 恢复只重算文件指纹，没有复用语义边界。
4. `delivery_engine.py` 主入口没有把 manifest 校验异常转换成稳定的结构化阻塞结果。
5. Reporter 将自由文本 `open_issues` 当成布尔值，无法可靠识别无问题文本或多个问题。
6. Runtime Adapter 返回了宿主 action 描述，但没有生产调用方，也不能真正调用 Codex/Claude 宿主工具。
7. Provider/PDLC 演进留下了无生产调用的派生常量、探测函数和重复指纹实现。
8. 自审发现 Snapshot 内容 fingerprint 未覆盖 `VERSION`，仅升级版本时会错误复用旧内容地址并在验证阶段阻塞。

## 影响范围

- Controller Snapshot 的来源隔离与自修改任务恢复。
- 动态 Provider 的发现、冻结和跨会话 Binding 恢复。
- 非法 Provider 配置的 CLI 交互。
- 最终报告的状态与待处理数量。
- 子代理能力声明、父控制器宿主调用边界和控制内核维护成本。

## 修复方案

- Provider Contract 提供统一 manifest 扫描和 stage 来源复验；generic manifest 明确冻结必需词与禁止词。
- Snapshot 使用共享 registry 清单，递归移除目录写权限，并把 `VERSION` 纳入内容 fingerprint；live trusted runner 先验证完整快照再执行允许的冻结 helper。
- Engine 捕获环境/manifest 校验异常，统一输出 `blocked/environment` 和退出码 2。
- Schema 将 `handoff.open_issues` 规范为字符串数组；旧明确无问题文本迁为空数组，其他旧文本迁为单元素数组。
- Runtime Adapter 只保留能力协商和宿主状态规范化，父控制器直接调用宿主工具。
- 删除确认无生产调用的兼容派生与重复 canonical fingerprint 实现，保留 v5/v6 状态迁移。

## 回归测试覆盖

- Snapshot：动态 Provider 冻结、全部中间目录只读、仅 VERSION 变化生成新地址、篡改后 trusted runner 在 helper 启动前阻塞。
- Provider：普通 Markdown 和含发布控制词的伪 TDD 来源在 Binding 恢复时阻塞。
- Engine：非法 manifest 无 traceback，结构化阻塞并返回退出码 2。
- Report：`No remaining scoped findings`、`0` 均为零项；两个结构化问题保持两项。
- Compatibility：旧 v5/v6 状态迁移、delivery state 转换和现有 Provider 选择回归。

## 验证结果

- 定向回归：Snapshot 8 项、Provider 5 项、Engine 30 项、Report 11 项、Runtime 4 项全部通过。
- 全量检查：4 个官方 Skill validator 和 190 项测试通过，退出码 0。
- 离线安装诊断：Codex Suite/Source 版本 0.12.1 完整，退出码 0。
- Plan Contract：validate 与 completion audit 均通过，`scope_drift=[]`。
- `git diff --check`：退出码 0。

## 假设与说明

- Snapshot 的只读权限用于防止普通误写；同一系统用户拥有主动 `chmod` 能力，因此执行边界还要求始终通过 live trusted runner 验证后启动冻结 helper。
- 旧自由文本无法可靠拆分成多个问题，兼容迁移只把非空非哨兵文本保存为一个问题；新写入必须使用列表。

## 上线前待办

无。此次未执行安装、发布、提交、tag、push 或 publish。
