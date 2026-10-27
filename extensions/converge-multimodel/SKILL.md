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

The controller or an authorized writable implementer creates complete documents
and other deliverables in agreed workspace files. Scout/reviewer inspect existing
files and return short observations; never ask them to put an entire deliverable
inside `finding.summary`. Before dispatch, observe the file using
`role_result.py observe` as described in [file delivery](../../references/multi-model.md#文件交付与证据核验-protocol-22).
Pass that reference and observed hash to the reader. Optional baseline generation
is not a prerequisite unless frozen acceptance actually requires it; decide this
before launch, without bypassing an already blocked run.

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


## Managed review and format failures

Managed Review v3 requires local source-reading tools. The current API-only
runner is diagnostic and must be rejected before a managed reviewer launch;
a workspace=read label alone does not supply source access. Check credentials
and current-source prerequisite review passes before persisting a launch.

A completed process with an invalid conclusion is blocked, not a successful
review or an unknown process. Preserve its original receipt. Protocol 21
permits exactly one explicit local format correction bound by recovery_of;
use the single-dispatch lifecycle and a corrected format prompt. Never retry
unknown exits, chain recoveries, reset review budgets, or turn a recovered
model conclusion directly into verified acceptance. See the bounded recovery
contract in the multi-model reference.
