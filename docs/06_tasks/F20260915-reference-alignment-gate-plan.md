# F20260915 — Reference Alignment Gate

## Goal

When a user declares a concrete implementation as the sole reference baseline, prevent target writes until relevant differences are classified; finish only when the remaining differences are explicitly allowed target-specific ones.

## Research and decisions

| Affected capability | Adopt / do not adopt | Reason | Behavior evidence |
| --- | --- | --- | --- |
| Trigger and progressive disclosure | Adopt a narrow root trigger plus one on-demand reference | The root Skill stays discoverable without turning ordinary links into gates. | `reference-alignment-gate` interaction scenario. |
| Reference receipts and behavior matrix | Extend the existing receipt to schema v3 with `alignment_bindings`; do not add another state record | The work item already freezes the target baseline and decisions; the receipt can additionally bind the comparison scope, differences and approved exception text without duplicating truth. | `test_reference_receipt.py` and `test_work_item.py` reject unapproved/out-of-scope exceptions and decisions absent from the work item. |
| Strict exact-file comparison helper | Do not add one | Relevant scope and target-specific exceptions need task judgment; a helper would either overreach across unrelated modules or create a second source of truth. | Rule requires an explicit per-difference classification and a final re-comparison. |
| Implementer launch binding | Extend the existing launch configuration with one fingerprint | A receipt fingerprint alone does not prove that the writer received the frozen target and user decisions. | Runner launch tests reject missing/mismatched target or decisions before dispatch. |
| Continued-work scope freshness | Reuse the existing work-item state for one scope-content fingerprint and final comparison | A second state record would duplicate the receipt; initial and final fingerprints distinguish pre-write drift from expected implementation changes. | Work-item tests reject a changed scope on resume and a missing/stale final comparison on completion. |
| Skill evaluation | Extend the existing replayable interaction catalog receipt | The prior booleans and counts were self-reported. A pass now binds each turn to host terminal evidence, transcript-derived question counts, workspace snapshots and verification evidence. | `scripts.test_interaction_smoke` rejects forged write, question and verification observations. |

## Execution plan

1. Add a failing interaction scenario in which implementation is authorized but a target-specific difference remains undecided; expected result is no write and one decision request.
2. Add the existing Converge root trigger and a short, on-demand reference-alignment procedure. Persist the comparison in the existing reference receipt for continued work and report it for inline work.
3. Bind external implementer launches to the exact target and approved decisions, then save and verify the continued-work scope snapshot and final comparison.
4. Bind passing smoke observations to host-terminal and per-turn evidence, then run direct regressions, deterministic evaluation preflight and the repository check.
