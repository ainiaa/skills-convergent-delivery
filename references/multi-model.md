# 多模型协作

用户明确说“使用多模型配合开发”时启用；普通任务保持原路径。默认顺序为：

```text
Sol high 设计 → Plan
→ Luna max 实现与真实测试
→ Terra xhigh 审计
→ 至多一次 Luna max 定向修复
→ Terra xhigh 复审与控制器最终验收
```

设计复核默认跳过。只有用户明确要求“设计复核”时，才在设计与 Plan 之间调用 Terra xhigh 的只读 `design_review` worker；它只修正/确认 Design Artifact，不能实现代码或跳过 Plan 校验。

配置支持多套命名 Profile；默认选择 `default_profile`。用户级默认配置：

```json
{
  "schema_version": 3,
  "default_profile": "default",
  "profiles": {
    "default": {
      "design": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
      "design_review": {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
      "implementation": {"model": "gpt-5.6-luna", "reasoning_effort": "max"},
      "audit": {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"}
    }
  }
}
```

配置优先级为显式 `--config`、项目 `.converge/multi-model.json`、用户级 `~/.convergent-delivery/multi-model.json`、内置默认。用下列命令输出模板：

```bash
mkdir -p ~/.convergent-delivery
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" config > ~/.convergent-delivery/multi-model.json
```

项目配置只覆盖该项目；`resolve` 自动按上述顺序发现配置。用户说“使用 `<profile>` 配置”时选择同名 Profile；未指定时使用 `default_profile`。也可在单次任务中直接指定角色，例如“设计用 Sol high、实现用 Luna max、审计用 Terra xhigh”；这只覆盖本次 Profile，不写回配置。命令等价形式为：

```bash
python3 "$CONVERGE_SKILL_DIR/scripts/multi_model.py" resolve \
  --profile <profile> --role design=gpt-5.6-sol@high \
  --role implementation=gpt-5.6-luna@max --role audit=gpt-5.6-terra@xhigh
```

设计、设计复核、实施和 OpenAI 审计可选 Sol/Terra/Luna；角色、权限、预算、修复上限和验收门禁不可由配置改变。

每个角色都使用冻结 profile：设计、设计复核和审计只读；实施可写且必须在 isolated worktree。设计结论输入 `converge-plan`，实施执行完整 Plan/capsule；PDLC Binding 存在时显式调用冻结的 `$pdlc-*` 入口。审计 finding 最多触发一次定向修复和一次复审；模型结论不能替代真实测试、源码指纹或发布授权。

若把 `audit` 改为 `glm-5.2/high`，它是外部只读审计叶子，使用 `GLM_API_KEY` 后可通过 `multi_model.py audit --execute --input -` 返回即时内容；不保存 prompt、密钥或审计文本到正式回执。当前 Codex Desktop 可将 OpenAI profile 映射为当前会话的真实 worker；宿主不能稳定指定模型或查询 worker 时输出 handoff，不伪造派发。
