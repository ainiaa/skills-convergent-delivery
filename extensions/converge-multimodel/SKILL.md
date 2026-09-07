---
name: converge-multimodel
description: Use Converge's multi-model runner, role dispatch, or model evaluation only when the user explicitly requests multiple model providers, independent model comparison, or bounded runner fan-out. Do not use for ordinary Converge delivery.
metadata:
  compatibility: Requires the registered Converge Suite and an explicit multi-model request.
---

# Converge Multi-model

This is an opt-in execution extension. Use it only where independent model
work has a concrete isolation or comparison benefit; a single controller stays
the default.

Create the controller snapshot with `--extension multimodel` before executing
its runner or evaluation helpers. The frozen descriptor is the authority for
the selected extension set. Read [multi-model guidance](../../references/multi-model.md)
only when this extension is selected.

Use `multi_model_repo_eval.py` for an explicit frozen Git-task comparison.
It defaults to a plan; `--allow-execute` creates only disposable fixtures and
worktrees, with one implementer and an optional read-only reviewer.
Reports separate `implementation_status` (frozen tests and scope) from
`execution_status` (all requested roles returned usable results). A missing or
failed reviewer makes the multi-role run incomplete without changing a passing
implementation verdict. `duration_ms` includes role execution; verifier time alone
does not measure model efficiency. These reports remain diagnostic.
