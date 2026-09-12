# Host Bridge v1

## Goal

Enable Converge evaluation to obtain lifecycle evidence from real Codex Desktop and Claude Code tasks. A local runner receipt is not host-observed evidence and must remain insufficient for the model evaluation gate.

## Scope

- Add one frozen `host-bridge-v1` protocol with Codex and Claude adapters.
- Allow the trusted Controller Snapshot to start an evaluator task, observe it, and record a bounded terminal receipt.
- Enable model evaluation only when every required host receipt is available and valid.

Out of scope: automatic recovery, retrying unknown tasks, preserving prompts or transcripts, changing ordinary runtime runners, and supporting any other host.

## Protocol

The bridge accepts only a frozen evaluator launch and exposes three operations:

1. `start` creates exactly one host task and returns its host ID, workspace, adapter ID, binary/schema fingerprint, and start time.
2. `observe` queries that exact host task and returns a host-reported nonterminal or terminal status.
3. `finalize` emits an immutable receipt containing the host ID, final status, timestamps, bounded result summary, and fingerprints of the frozen launch and adapter protocol.

Only the trusted snapshot may invoke these operations. Candidate code, its tests, and externally supplied JSON cannot create or modify a receipt. Receipt data never includes the prompt, task transcript, or chain of thought.

## Adapters

### Codex Desktop

The adapter uses the local Codex app-server thread/turn protocol. Before launch it verifies the frozen Codex binary fingerprint and the generated app-server schema fingerprint. It starts a dedicated evaluator thread, polls only that thread/turn, and reads the host-reported terminal result. Because app-server is experimental, an unavailable endpoint or any schema mismatch returns `unavailable`; no compatibility guessing is permitted.

### Claude Code

The adapter starts one named background session, then uses `claude agents --json` and the session's terminal log/status to observe it. It binds the Claude binary fingerprint, session ID, workspace, and frozen launch. A missing session, ambiguous session identity, timeout, or nonterminal disappearance is `unknown` or `unavailable`, never success.

## Evaluation behavior

The evaluator requires a valid finalized receipt for each sample. Known acceptance and selected history scenarios use the existing sample rules; critical scenarios require three distinct host tasks. A host task may be observed repeatedly but never retried under the same sample identity. Any `unavailable`, `unknown`, malformed, stale, or mismatched receipt leaves the scenario `uncovered` and the release status `uncovered`.

## Safety and verification

- No fallback to `codex exec`, `claude --print`, local process output, or model self-report.
- Start/observe/finalize transitions are idempotent for one frozen sample identity and reject conflicting host IDs.
- Unit tests use fake host transports only to validate protocol parsing and error handling; they are diagnostic, not host evidence.
- Host smoke tests run each adapter against a real task and prove launch identity, observation, terminal receipt validation, schema/binary drift rejection, timeout handling, and no prompt/transcript persistence.

## Completion criteria

The model evaluation preflight reports eligible only when both adapters are installed and pass capability checks. A complete evaluation report contains validated, host-observed receipts for all required samples; otherwise it remains `uncovered` with the precise missing capability or receipt reason.
