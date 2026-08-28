---
name: converge-autonomy
description: Enable Converge's explicit autonomous delivery continuation or managed service only when the user asks for autonomous continuation, recovery, or a background delivery service. Do not use for ordinary single-session delivery.
metadata:
  compatibility: Requires the registered Converge Suite and explicit autonomy Hook enablement.
---

# Converge Autonomy

This is an opt-in extension. It owns Stop-hook continuation, bounded recovery,
and the macOS service adapter; it does not replace ordinary `converge` work.

Start autonomous work through `autonomy_begin.py`. That command freezes the
`autonomy` extension set with the run. Read the core [execution control](../../references/execution-control.md)
and [runtime adapters](../../references/runtime-adapters.md) before changing a
continuation or service configuration.

The Skill is registered with the Suite, but Hook enablement and removal require
the explicit installer options. A service is separate from a hook and is only
for the documented low-risk route.
