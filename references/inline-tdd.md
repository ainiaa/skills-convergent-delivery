# Inline TDD

局部、单 writer 的 `inline` 任务只做以下闭环：冻结当前范围，先得到可执行红灯，做最小修复，运行对应绿灯，并报告实际命令与结果。

只有运行时风险、Provider binding 或计划明确要求时，才展开 [完整 TDD/Provider 证据](tdd-providers.md)。不要因简单修复加载 worker、自治、覆盖率解析、mutation 或多模型协议。

没有可运行测试时如实报告 `uncovered`，不得以模型自述替代验证。
