# Codex Host Bridge Daemon Recovery Design

## Goal

Allow a `host-bridge-v1` Codex evaluator task to be observed after the bridge process or machine restarts. Recovery must never create a replacement task, reuse a mismatched task, or turn an unknown task into success.

## Chosen approach

Use the native `codex app-server daemon` and `codex app-server proxy` surface.

1. The trusted bridge performs the explicitly authorized one-time `daemon bootstrap`, then `daemon start` during host preflight and again before starting a Codex task; failure is reported as unavailable.
2. It starts a non-ephemeral task through `app-server proxy`; the task remains owned by the Codex daemon rather than the bridge process.
3. It persists one recovery record below the evaluated repository's Git common-dir: `.git/convergent-delivery/host-bridge/<package-fingerprint>.json`.
4. A later bridge process reconnects through `proxy`, resumes exactly the stored task ID, and observes exactly the stored turn ID.

The recovery record contains only protocol/package fingerprints, task ID, turn ID, workspace, daemon/version fingerprint, and lifecycle status. It never stores prompt text, model output, transcript, judge output, or chain of thought.

## State and transitions

`start` atomically writes `started` only after the daemon returns one task ID and one turn ID. A subsequent start with the same package returns that record; a conflicting identity is rejected.

`observe` reads the record and reconnects through `proxy`. It accepts only the exact task/turn and a known host terminal status. `completed` permits the frozen judge; `failed` and `interrupted` remain terminal receipts but leave evaluation uncovered. Missing daemon, missing socket, schema/version drift, mismatched task, or an unresumable task writes `unknown`; it never launches another task.

`finalize` atomically writes the bound terminal receipt and removes no evidence. Repeated finalize returns the same receipt only when every fingerprint matches.

## Failure boundaries

Daemon bootstrap/start failure, host upgrade/schema drift, disk-record corruption, and machine restart are explicit unavailable/unknown states. The bridge does not install a custom LaunchAgent, restart a failed evaluator task, or fall back to `codex exec`.

The only external host mutation is the user-authorized native Codex daemon bootstrap. Project recovery records use the existing Git common-dir convention and are scoped to one package fingerprint.

## Verification

Tests must prove:

- a start record is idempotent and contains no prompt;
- a fresh bridge instance reconnects through proxy and observes the same task/turn;
- a conflicting record, daemon/schema drift, or unavailable proxy becomes unknown/unavailable without a second start;
- a real smoke creates one read-only task, terminates the bridge client, reconnects, obtains the exact terminal status, and finalizes the frozen `true` judge;
- normal host-bridge, evaluator, snapshot, and capsule-dispatch regressions remain green.

If the native daemon cannot resume an active task after a new proxy connection, the feature remains `uncovered`; no custom daemon is introduced in this change.
