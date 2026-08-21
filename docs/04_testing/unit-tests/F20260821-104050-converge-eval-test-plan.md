<!-- PDLC-TRACE -->
<!-- 功能ID: F20260821-104050 -->
<!-- 功能名称: converge-eval -->
<!-- 阶段: 测试 -->
<!-- 前置文档: docs/02_design/architecture/F20260821-104050-converge-eval-arch.md -->

# 测试计划

运行 `PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-eval/scripts/test_eval_contract.py`。

- 正常：自修改冻结 control，并与 candidate 使用同场景判定。
- 边界：关键决策至少多个 fresh samples；单次 PASS 不代表稳定。
- 历史：两个 touched surfaces 选择且只选择全部匹配逃逸场景。
- 分类：四类结果固定、独立。
- 异常：三次修订上限、首次无改善停止升级、外部副作用禁止。

## 红灯证据

2026-08-21：6 个测试均因 `skills/converge-eval/SKILL.md` 不存在而 error，exit 1。实现首轮为 5 通过、1 失败，准确发现两条 catalog source 路径拼写错误。

## 绿灯证据

2026-08-21：修正 catalog 数据后 6/6 通过，exit 0；两个 JSON 与 PDLC state 均可由 `jq -e` 解析，`git diff --check` exit 0。官方 quick validator 因当前 Python 缺少 `PyYAML` 未启动（exit 1），未安装新依赖。

## 自审记录

4/4 验收标准均有契约测试；覆盖正常、边界、历史选集和异常停止/权限场景。
