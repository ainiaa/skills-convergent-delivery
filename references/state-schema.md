# 轻量状态 Schema v1

仅用于跨服务、跨会话或用户要求恢复的 `convergent-delivery` 任务。状态文件不保存密钥、Cookie、请求正文或敏感业务数据。

```json
{
  "schema_version": 1,
  "run_id": "run-<唯一标识>",
  "workspace": "/absolute/workspace/path",
  "baseline": {
    "commit": "起始提交或明确的不可用标记",
    "diff_fingerprint": "起始diff指纹"
  },
  "scope_fingerprint": "已冻结范围的指纹",
  "current_stage": "scope | round-1-build | round-1-semantic-review | verify-round-1 | round-2-risk-review | verify-final",
  "requires_stability_round": false,
  "status": "active | complete | blocked",
  "blocked_reason": "status 为 blocked 时必填",
  "handoff": {
    "goal": "当前目标",
    "last_verification": "最后一次验证的命令和结果",
    "open_issues": "无或待解决问题",
    "next_action": "唯一下一步"
  }
}
```

更新状态时，先写同目录临时文件，校验 JSON 后以原子 rename 替换原文件。恢复时必须优先指定 `run_id`；未指定时，只有工作区、基线和范围均匹配的候选恰好一份才可继续，多个候选一律阻塞。

恢复或外层循环前运行：

```bash
python3 scripts/delivery_next.py --state <state-file> --run-id <run-id>
```

脚本 stdout 只会输出一个 token：`round-1-build`、`round-1-semantic-review`、`verify-round-1`、`round-2-risk-review`、`verify-final`、`complete` 或 `blocked`。它只读状态，不写文件、不执行代码。
