---
name: converge-multimodel
description: Use Converge's multi-model runner, role dispatch, or model evaluation only when the user explicitly requests multiple model providers, independent model comparison, or bounded runner fan-out. Do not use for non-multi-model Converge delivery.
metadata:
  compatibility: Requires the registered Converge Suite and an explicit multi-model request.
---

# Converge Multi-model

This is an opt-in execution extension. Use it only where independent model
work has a concrete isolation or comparison benefit; a single controller stays
the default. It is not a complete role-level model orchestration: `serial`
roles stay on the current controller and do not switch models from the profile.

For an ordinary delivery, follow the root `converge` controller contract and
select this extension only for a phase with demonstrated isolation or
independent-review benefit. Freeze and run only that `agent` dispatch through
the runner lifecycle. Do not create a runner merely to make every role use a
different model.

Read-only is a workspace boundary, not a universal side-effect boundary. The
Codex runner inherits the user's MCP configuration and the full host process
environment, including credentials such as API keys, proxy settings, and host
configuration variables; the Suite does not sanitize or allowlist it. The Suite
also does not provide a no-MCP configuration or an explicit tool allowlist, so
this boundary is `uncovered` unless the controller independently verifies such
a configuration. Do not use the runner for untrusted instructions or sensitive
external actions without that verification.

Create the controller snapshot with `--extension multimodel` before executing
its runner or evaluation helpers. The frozen descriptor is the authority for
the selected extension set. Read [multi-model guidance](../../references/multi-model.md)
only when this extension is selected.

`desktop-task` and `audit --execute` are explicit direct operations outside
the normal role-flow runner lifecycle. Follow their own frozen action or
diagnostic receipt rules; do not treat either as a completed model worker.

Use `multi_model_repo_eval.py` for an explicit frozen Git-task comparison.
It defaults to a plan; `--allow-execute` creates only disposable fixtures and
worktrees, with one implementer and an optional read-only reviewer.
Reports separate `implementation_status` (frozen tests and scope) from
`execution_status` (all requested roles returned usable results). A missing or
failed reviewer makes the multi-role run incomplete without changing a passing
implementation verdict. A reviewer result with findings or a next action other than `verify`
makes the overall multi-role evaluation fail while preserving that implementation
verdict. `duration_ms` includes role execution; verifier time alone
does not measure model efficiency. These reports remain diagnostic.

## Desktop isolated implementer task

The `multi_model.py desktop-task` command emits only a frozen `create_thread`
request. It does not, and cannot, call Desktop MCP tools itself. When this
extension is explicitly selected and the host exposes the required tools, the
host controller performs this exact lifecycle:

1. Generate the action with `desktop-task`, then call `create_thread` using
   its `arguments` unchanged.
2. Build `creation_receipt(action, create_thread_result)` only from that live
   tool result. A `clientThreadId` is indeterminate, not a confirmed task.
3. Generate `query_action(receipt)` and call `wait_threads` using its
   `arguments` unchanged.
4. From a terminal `wait_threads` result for that exact task, call
   `terminal_observation(receipt, query, normalized_result)`, where
   `normalized_result` retains only `tool`, terminal `status`, and `task_ref`.
5. Only then call `archive_action(receipt, observation)` and invoke
   `set_thread_archived` with its `arguments` unchanged.

The controller must not call `archive_action` from a model-supplied status
string, and it leaves tasks unarchived when the status is non-terminal,
missing, or the task reference differs. This is a host-controller protocol,
not an automatic continuation mechanism; a real smoke requires an explicitly
requested Desktop task.
