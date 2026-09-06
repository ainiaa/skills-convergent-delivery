<!-- PDLC-TRACE -->
<!-- 功能ID: B20260906-195330 -->
<!-- 功能名称: execution-evidence-five-fixes -->
<!-- 阶段: review -->
<!-- 前置文档: 无 -->
<!-- 创建时间: 2026-09-06T19:53:30+08:00 -->

# 五项执行证据缺陷修复

作者：Jeff.Liu

基线：`05230ec4cf2e9762acb8ef802205edf25dfa0615`。本轮范围固定为上轮审查确认的五项缺陷，未安装工具、提交、推送或调用真实模型。

| 缺陷 | 根因与修复 | 回归 |
|---|---|---|
| 零测试 GREEN / 输出参数冒充 selector | 实际执行汇总写入 Evidence 指纹；GREEN 要求非空执行，pytest 输出选项值不能充当位置选择器 | Python 3.9 实际 unittest 零测试、全跳过与正常执行，以及 pytest 选项反例；拒绝空目标混入无关测试借用计数 |
| echo 冒充 mutation | PIT Maven 作用域、正数变异/测试和 KILLED 状态共同验证；其他工具不能凭成功退出放行 | echo、零变异、存活、超时、未执行/未覆盖、异常、重复作用域拒绝；正常协议通过 |
| closure 与 Plan 图证据遗漏 | 三入口共用结构化图校验；基线和最终源码分别绑定，索引文件和调用边由公共 runner 读取 | 单独哈希、缺少 graph_check、无关输出、不存在路径/边拒绝；合法协议及完整状态正例仍通过 |
| 图子进程超时后写入 | 抽取既有进程组执行/清理逻辑给主命令和所有子查询复用；共享显式超时预算 | 真实后代延迟写入测试在返回后不产生文件，源码指纹保持一致 |
| 异常 JSON 原始 AttributeError | 验证 object/list/嵌套元素形状，异常结果不生成 graph_check；清场不明单独传播 | 合法 JSON 的错误形状受控失败，不签发图证明 |

实现取舍和原始参考见 [机制记录](../../02_design/architecture/F20260824-converge-truth-reference-review.md)。复用 Evidence v2 和现有 unittest，无新增依赖、代理、控制循环或运行时状态真源。

先运行新增七个回归用例确认红灯，原输出在本机 `/tmp/converge-five-fixes-red.log`；其中包含六个失败及错误 JSON 的四个子场景异常。同根因变体另先红后绿验证空目标混入无关测试的情况。五项缺陷已登记到历史场景 catalog；本轮正式 Eval 仍使用旧冻结快照预检，未用更新后的 catalog 为自身放行。修复后的最终验证结果如下。

## 验证结果

- `bash scripts/check.sh --full`：退出码 0；56 组、933 个测试、7 个官方 Skill 校验全部通过。检查前后 Source Receipt 完全一致。
- Python 3.9：30 个定向用例通过，包含实际零测试、混入无关测试、子进程超时清理及合法结果正例。
- TDD 完整测试文件：41 个用例通过。
- 本轮没有修改或移除原检查命令；旧测试夹具补齐真实协议字段，保留其原有失败目标和断言。
- 全量运行记录：`/tmp/converge-five-full.log`；实际 argv、退出码和源码回执：`/tmp/converge-five-full-receipt.json`。
- 旧快照 evaluator preflight：退出码 2、`unavailable_host_bridge`；正式 Eval 保持 uncovered。
- 复核为同会话自审，`independent=false`；本地确定性回归不能替代正式独立模型验收。

全量检查后仅填写本文验证结果和本地 PDLC 收尾记录；实现、测试、契约与 catalog 保持受检版本。

## 兼容性与未覆盖边界

- 旧 GREEN、mutation 和 Plan 图回执缺少新增观察时必须重新采集，不迁移为通过。
- PIT 协议适配用真实子进程和官方输出格式夹具验证；未安装 PIT，未执行真实 JVM mutation campaign。
- Gradle 需要本次输出可解析的测试执行汇总；静默/定制日志和未知 mutation 工具保持 uncovered，不读历史报告补证据。
- 静态图只证明当前索引内的直接关系，不能保证分析器发现所有动态调用；文件/边数量和图查询时间有界。
- 正式 evaluator 缺少真实宿主 bridge，预检返回 uncovered。本地测试不冒充独立模型 Eval 或收益证明；本仓 native coverage 配置仍为 uncovered，未更改原检查命令。


## 后续审查修复：结果分类与索引内容（基线 d9a9847）

- `successful-process-hides-failed-test-outcomes`：真实 unittest expectedFailure 和返回码 0 的失败汇总仍可作为 GREEN。现在保留结果分类，要求真实 passed 且无失败、错误或预期失败结果；对应 `test_real_expected_failure_is_not_green`、`test_success_exit_cannot_hide_failed_runner_outcomes` 和正常结果/旧回执回归。
- `clean-graph-status-hides-stale-index-content`：本仓真实 CodeGraph 的 clean status 掩盖已过期源码。现在只读 files.content_hash，核对当前源码清单并比较查询前后数据库/WAL 摘要；对应 `test_clean_status_cannot_hide_stale_index_contents` 的正常、保留尺寸/mtime 的编辑、已提交新增、删除、损坏及查询中变化场景，同时覆盖 impact/closure。

本轮参考取舍、适配边界和未覆盖能力见 [机制记录](../../02_design/architecture/F20260905-known-review-fixes.md)。本仓真实旧索引已被新 helper 拒绝签发 graph_check，未自动重建索引；协议夹具不是实际模型或 JVM 执行证明。
