<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-004423 -->
<!-- 功能名称: converge-control-kernel -->
<!-- 阶段: 设计 -->
<!-- 前置文档: docs/01_requirements/prd/F20260821-004423-converge-control-kernel-prd.md -->
<!-- 创建时间: 2026-08-21T00:48:00+08:00 -->

# Converge Control Kernel 架构设计

## 1. 设计原则

- 控制内核只做选择、冻结、校验、观察和报告，不执行 Provider 声明的任意命令。
- Provider Contract、Runtime Adapter、Reporter 是数据契约；宿主动作仍由宿主已有工具执行。
- 父控制器是状态唯一 writer；worker 只产生客观 milestone。
- 快照与目标 workspace 分离；当前任务永远从启动快照加载控制协议。
- 使用 Python 标准库，保留有界最新快照，不建 daemon、RPC 或事件日志。

## 2. 组件与职责

### 2.1 Provider Contract（`scripts/provider_contract.py`）

- 解析并严格校验 Provider Schema。
- 将 task kind 的 manifest、task contract、真实入口与显式 closure 解析为 canonical reference。
- 生成 `contract_fingerprint` 和 `source_fingerprint`；validate 时逐项重算。
- Provider Binding 仅组合 workflow 与 stage reference；其 canonical JSON 产生 `binding_fingerprint`。

共享模块由 resolver 与 resume validator 复用，消除两套字段白名单和指纹算法。

### 2.2 Provider Resolver（`scripts/delivery_engine.py`）

- auto 顺序固定：兼容 workflow（按 ID）→适配 stage（manifest ID 顺序）→generic→native。
- `--provider <id>` 为精确选择；不存在、不兼容或来源缺失均阻塞，不回退。
- `--mode native|pdlc` 作为兼容入口映射到精确 workflow。
- PDLC 缺失时 Native 使用自身入口与闭包完整绑定，可独立走 Native 协议。

### 2.3 Runtime Adapter（`scripts/runtime_adapter.py`）

采用无副作用的能力协商与结果规范化：

| profile | dispatch | query | wait | interrupt | 自动 worker |
|---|---:|---:|---:|---:|---:|
| codex | 按会话暴露能力 | 必须 | 可选 | 可选 | 仅 dispatch+query |
| claude-code | 按会话暴露能力 | 必须 | 可选 | 可选 | 仅稳定 ref+query |
| single-context | 否 | 否 | 否 | 否 | 否，manual handoff |

Adapter 只接受 capability JSON，并规范化宿主状态为 `working|completed|interrupted|blocked`。它不返回可执行 action；持有 `{run_id, worker_ref}` registry 的父控制器直接调用宿主工具并执行所有权/终态检查。`wait` 超时仍是 working，绝不伪造终态。

### 2.4 Progress（`scripts/delivery_progress.py`）

- `milestone`：worker 提供 phase/milestone/activity/evidence/next_action，父控制器盖时间戳并令 objective revision +1。
- `observe`：父控制器输入 Runtime query 结果生成 heartbeat，沿用最近客观字段，objective revision 不变。
- `status`：按 `(worker ref, status, objective revision, host status)` 生成友好行；与 `report_history` 指纹相同则不输出；无百分比、ETA。

### 2.5 Controller Snapshot（`scripts/controller_snapshot.py`）

- `create --source <suite> --root <control-root>` 使用与 resolver 相同的 manifest 扫描，将协议控制文件与完整 `providers/*.json` registry 复制到基于内容 hash 的只读快照目录。
- snapshot descriptor 冻结 source/control/root 绝对路径、包版本、协议版本与内容 fingerprint；fingerprint 覆盖 VERSION、root、中间目录和文件，且必须与 source/目标 workspace 隔离。
- live `run --descriptor <snapshot-or-state> --script <helper> -- ...` 在导入冻结模块前验证 descriptor、目录权限和完整 fingerprint，再 `exec` 允许的 helper；不得直接执行 snapshot Python 文件。
- 状态的 controller identity 引用 descriptor；resume 只验证 snapshot，不读取目标 workspace 活动源码。
- snapshot 闭包包含 `SKILL.md`、状态/报告/TDD references、运行 helper 与 Provider registry；快照内 resolver 在无活动 Suite/PDLC 时仍可 auto 选择 Native，篡改或替换任一文件失败。

### 2.6 Reporter（`scripts/delivery_report.py`）

- summary：结果、关键改动、验证、交付过程和必要下一步。
- diagnostic：仅 `--detail` 或异常结果追加 controller/provider/worker/check 等技术层。
- JSON 同时提供 `summary` 与可选 `diagnostic`，文本默认只渲染 summary。
- `handoff.open_issues` 使用结构化字符串数组；旧无问题文本迁为空数组，其他旧文本迁为单元素数组。

## 3. 状态与兼容

- 单任务 Schema v7 对新任务增加可选 `controller.snapshot` descriptor；Provider reference 增加 `contract`、`contract_fingerprint`、入口/closure 来源清单。
- 旧 v7 无 snapshot 状态继续以原活动协议指纹验证，不伪造快照迁移；新持久任务必须在初始状态写入前创建快照。
- `provider_binding`、`controller` 继续是 immutable fields。
- worker progress 仍只保留最新值；report history 仅保留有界去重指纹（最多 20 项）。

## 4. 错误与安全

- 路径必须绝对且 resolve 后位于声明 root；拒绝 `..`、缺失文件、symlink 逃逸。
- manifest 无 command/shell/priority 字段；Runtime Adapter 不接受可执行 command。
- query/wait/interrupt 由父控制器在调用宿主工具前校验 run owner、精确 ref 和协商能力；能力不足返回结构化 `manual`。
- snapshot 使用临时目录、fsync 后原子 rename；已存在同 hash snapshot 只验证复用。

## 5. 验证映射

| 验收 | 测试 |
|---|---|
| Binding 任一来源变化阻塞 | provider contract 单元测试 + state resume 测试 |
| auto 稳定、显式 ID | delivery engine 选择测试 |
| Runtime 协商与宿主状态规范化 | runtime adapter 正常/边界/异常测试 |
| milestone/heartbeat/去重 | delivery progress 与 state transition 测试 |
| 自修改快照 | snapshot 创建、活动源码变化、快照篡改测试 |
| 分层报告 | ready/attention/blocked 与 detail 测试 |
| 公共契约 | skill、README、install doctor、完整 check |

## 6. 自审记录

- PRD P0/P1 覆盖：8/8。
- API/DB：不涉及网络 API 或持久业务数据库，跳过对应设计。
- 安全边界：无任意命令、无后台进程、无共享写、无无限日志。
- 一次复查结果：0 个未解决问题。
