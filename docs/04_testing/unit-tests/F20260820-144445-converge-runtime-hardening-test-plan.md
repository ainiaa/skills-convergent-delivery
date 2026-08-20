<!-- PDLC-TRACE -->
<!-- 功能ID: F20260820-144445 -->
<!-- 功能名称: converge-runtime-hardening -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260820-144445-converge-runtime-hardening-arch.md -->

# 测试计划

| 编号 | 场景 | 预期 |
|---|---|---|
| UT-01 | Claude 只有根 Skill | version 显示 incomplete；doctor 非零并列出两个缺失入口 |
| UT-02 | Suite 完整 | version/doctor 显示 complete，doctor 输出依赖与 engine |
| UT-03 | ready state | 报告器输出轮数、修复数、0 待处理和验收摘要 |
| UT-04 | decision/blocked state | 不误写 ready，待处理数与下一步稳定 |
| UT-05 | 非法 state | 报告器退出非零，不生成成功回执 |
| CT-01 | 运行时适配 | Codex/Claude/手工降级、稳定 ref、查询后重派边界齐全 |
| E2E-01 | fake host 两批接力 | 每批仅派发一次，receipt 后顺序推进 |
| E2E-02 | 断线恢复 | 查询原 ref；未知时阻塞，不重派 |
| FT-01 | 真实 Agent 临时仓库 | 留存独立运行的输入、任务引用和结果 |

红灯必须来自能力缺失，而不是测试语法或环境问题。实现后运行 `bash scripts/check.sh` 和三个 Skill 结构校验。
