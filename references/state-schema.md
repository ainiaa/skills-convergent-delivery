# 轻量状态 Schema v5

仅用于跨服务、跨会话或用户要求恢复的单个 `converge` 任务。状态文件不保存密钥、Cookie、请求正文或敏感业务数据。多 Batch 计划使用独立的 [Batch Protocol v1](../skills/converge-batch/references/batch-contract.md) 和 `~/.convergent-delivery/batch-state/`，不得把两种状态合并。

```json
{
  "schema_version": 5,
  "run_id": "run-<唯一标识>",
  "repo_id": "git common directory 的绝对路径",
  "task_key": "已冻结范围的确定性指纹",
  "writer_id": "当前写入者的唯一标识",
  "revision": 0,
  "workspace": "/absolute/workspace/path",
  "baseline": {
    "commit": "起始提交或明确的不可用标记",
    "diff_fingerprint": "起始diff指纹"
  },
  "scope_fingerprint": "已冻结范围的指纹",
  "engine": {
    "name": "native-v1 | pdlc-v1 | superpowers-tdd-v1 | mattpocock-tdd-v1 | generic-tdd-v1",
    "selection": "auto | explicit",
    "reason": "引擎选择或降级的客观原因",
    "pdlc_root": "仅 pdlc-v1：PDLC 源码根目录或已安装 skills 根目录的绝对路径",
    "feature_id": "仅 pdlc-v1：PDLC feature/fix ID",
    "task_kind": "仅 pdlc-v1：feature | fix",
    "pdlc_fingerprint": "仅 pdlc-v1：所需 PDLC Skill 内容摘要",
    "tdd_skill_path": "仅第三方 TDD 引擎：被冻结的 SKILL.md 绝对路径",
    "tdd_skill_fingerprint": "仅第三方 TDD 引擎：该 SKILL.md 的内容摘要"
  },
  "current_stage": "native-v1 和第三方 TDD 引擎：scope | round-1-build | round-1-semantic-review | verify-round-1 | round-2-risk-review | verify-final；pdlc-v1: pdlc-run",
  "requires_stability_round": false,
  "status": "active | complete | blocked",
  "blocked_code": "decision | environment | no_progress | budget_exhausted（status 为 blocked 时必填）",
  "blocked_reason": "status 为 blocked 时必填",
  "ledger": {
    "completed_rounds": 0,
    "repair_fingerprints": ["阶段 + 流程/契约 + 违反行为 + 根因"],
    "checks": [
      {"stage": "阶段", "command": "已脱敏命令", "result": "pass | fail | unknown"}
    ],
    "acceptance": [
      {"criterion": "验收项", "evidence": "测试或命令", "result": "pass | fail | unknown", "freshness": "fresh | stale | unavailable"}
    ],
    "report_history": {
      "last_outcome": "ready | attention | decision | blocked",
      "reported_fingerprints": ["已向用户说明的问题或待决项指纹"],
      "summary_fingerprint": "上一份用户回执的指纹"
    }
  },
  "handoff": {
    "goal": "当前目标",
    "last_verification": "最后一次验证的命令和结果",
    "open_issues": "无或待解决问题",
    "next_action": "唯一下一步"
  }
}
```

`repo_id`、`task_key`、`writer_id`、`revision` 是写入归属信息：`repo_id` 使用 `git rev-parse --git-common-dir` 解析后的绝对路径；`task_key` 必须由 `scripts/delivery_task_key.py` 生成；`writer_id` 来自成功获取的 lease；每次成功状态写入将 `revision` 加一。`ledger` 保留跨会话防重复修复、最终验收和增量回执所需的最小证据，命令参数必须脱敏。`report_history` 仅用于避免重复汇报，不保存用户原文、密钥或业务敏感数据。

`engine` 是任务开始后不可静默改变的执行契约。`native-v1` 不填写第三方或 PDLC 路径；`superpowers-tdd-v1`、`mattpocock-tdd-v1`、`generic-tdd-v1` 必须填写 `tdd_skill_path` 与 `tdd_skill_fingerprint`，并使用原生阶段；`pdlc-v1` 必须填写 `pdlc_root`、`feature_id`、`task_kind` 与 `pdlc_fingerprint`，且 `current_stage` 只能为 `pdlc-run`。每次写入或恢复都会重新核验对应文件内容；路径、版本或内容变化一律环境阻塞，不能换一个来源继续。PDLC 的细粒度阶段、检查和产物继续只保存在 `docs/.pdlc-state/<feature-id>.json`；本 state 只记录协调层事实，不能复制或覆盖其状态。

状态根目录固定为 `~/.convergent-delivery/state/`，供 Codex 与 Claude Code 共用。正式路径只能由 `repo_id`、`task_key` 和 `run_id` 推导；更新时先续期 lease，再将完整 JSON 通过 `delivery_state.py write --input -` 的 stdin 提交。脚本不接受任意 `--state` 路径或外部候选文件，校验活动 lease、writer 和 expected revision 后在正式文件同目录原子写入。恢复时必须指定 `run_id`、`writer_id` 和 `revision`；未指定时一律阻塞。

恢复或外层循环前运行：

```bash
python3 scripts/delivery_state.py path --repo <repo-id> --task-key <task-key> --run-id <run-id>
python3 scripts/delivery_next.py --state <state-file> --run-id <run-id> \
  --writer-id <writer-id> --revision <revision>
```

脚本 stdout 只会输出一个 token：内置或第三方 TDD 状态的 `round-1-build`、`round-1-semantic-review`、`verify-round-1`、`round-2-risk-review`、`verify-final`；PDLC 状态的 `pdlc-run`；或终态 `complete`、`blocked`。它只读状态，不写文件、不执行代码。
