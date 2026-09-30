# Weekly Skill Review Toggle Implementation Plan

> **For agentic workers:** Execute inline in this session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-off project switch for the weekly Skill improvement review, with the scheduled run limited to evidence review and candidate reporting.

**Architecture:** A small stdlib `tomllib` policy reader checks `.convergent-delivery/skill-improvement.toml`; a missing file means disabled, and malformed configuration fails closed. A weekly Codex heartbeat checks the policy first, reads only durable defect/evaluation artifacts when enabled, and reports a candidate or no-op without running SkillOpt training or modifying Skills.

**Tech Stack:** Python 3.11+ standard library, unittest, Codex heartbeat automation.

---

### Task 1: Lock the off-by-default policy in tests

**Files:**
- Create: `scripts/test_skillopt_policy.py`
- Modify: `scripts/test_skill_contracts.py`

- [ ] Test missing config and explicit `enabled = false` both skip review.
- [ ] Test explicit `enabled = true` enables review.
- [ ] Test malformed TOML and a non-boolean `enabled` value fail closed.
- [ ] Add a contract test that the user-facing policy documents the ignored private config path and prohibits automatic Skill changes.
- [ ] Run the new tests and confirm they fail because the policy reader and contract are not implemented.

### Task 2: Implement the deterministic switch

**Files:**
- Create: `scripts/skillopt_policy.py`
- Modify: `scripts/check.sh`

- [ ] Read `.convergent-delivery/skill-improvement.toml` with `tomllib`; treat a missing file as disabled.
- [ ] Reject malformed TOML and non-boolean `enabled` values with a nonzero status.
- [ ] Print a compact JSON policy receipt so the weekly heartbeat can stop before loading evidence when disabled.
- [ ] Register the test module in the full check list.
- [ ] Run the new tests and the Skill contract tests.

### Task 3: Document the weekly review boundary and enablement

**Files:**
- Modify: `docs/02_design/architecture/self-improving.md`
- Modify: `SKILL.md`
- Modify: `scripts/test_skill_contracts.py`

- [ ] Document how to opt in by creating `.convergent-delivery/skill-improvement.toml` with `skill_review.enabled = true`.
- [ ] Keep the weekly review read-only: inspect durable defect/evaluation evidence, avoid raw conversation harvesting, and report candidates without launching training or changing Skill/evaluation files.
- [ ] Document that absent or invalid configuration does not enable the review.
- [ ] Verify the new contract tests pass.

### Task 4: Register the weekly Codex heartbeat

**Files:**
- Create or update: one weekly heartbeat automation attached to this local project thread.

- [ ] Run the policy helper first; if disabled, end quietly.
- [ ] When enabled, inspect only durable defect and evaluation records for a new, recurring, evidenced Skill issue.
- [ ] Report only actionable candidates; make no repository edits and keep unchanged weeks silent.

### Task 5: Verify and record the outcome

- [ ] Run the focused policy and contract tests.
- [ ] Run the project check/coverage gate and report any unrelated existing gate failures accurately.
- [ ] Run `git diff --check` and confirm pre-existing user changes remain untouched.

Commits are omitted because the shared worktree already contains unrelated uncommitted changes.
