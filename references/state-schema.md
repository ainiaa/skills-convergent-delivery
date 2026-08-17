# 轻量状态 Schema v2

仅用于跨服务、跨会话或用户要求恢复的 `convergent-delivery` 任务。状态文件不保存密钥、Cookie、请求正文或敏感业务数据。

```json
{
  "schema_version": 2,
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

`repo_id`、`task_key`、`writer_id`、`revision` 是写入归属信息：`repo_id` 使用 `git rev-parse --git-common-dir` 解析后的绝对路径；`task_key` 与冻结范围一致；`writer_id` 来自成功获取的 lease；每次成功状态写入将 `revision` 加一。状态不能由没有当前 lease 的 writer 覆盖。

更新状态时，先续期 lease，再写同目录临时文件，校验 JSON 后以原子 rename 替换原文件。恢复时必须优先指定 `run_id` 和 `writer_id`；未指定时，只有工作区、基线和范围均匹配的候选恰好一份才可继续，多个候选一律阻塞。

恢复或外层循环前运行：

```bash
python3 scripts/delivery_next.py --state <state-file> --run-id <run-id> \
  --writer-id <writer-id> --revision <revision>
```

脚本 stdout 只会输出一个 token：`round-1-build`、`round-1-semantic-review`、`verify-round-1`、`round-2-risk-review`、`verify-final`、`complete` 或 `blocked`。它只读状态，不写文件、不执行代码。
