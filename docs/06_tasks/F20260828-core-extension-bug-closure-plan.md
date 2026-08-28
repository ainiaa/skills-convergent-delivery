# Core + Extension Bug Closure Plan

Baseline: `b8d58e466b6a4eb3f53cf473da708d5324155f65` (clean source receipt)

Validated Plan v6: `plan-core-extension-bug-closure-20260828`; execution is sequential with no commit checkpoint.

1. Make extension uninstall remove only its extension and host hook, preserving the core Suite.
2. Centralize current and v16 snapshot extension resolution, and declare each extension's files explicitly.
3. Bind full-closure CodeGraph receipts to the frozen scope and closure matrix rather than any non-empty query.
4. Keep Hook autonomy independent of the multimodel runtime; add it only for service mode.
5. Update the user-facing boundary description and run targeted plus full verification.

Decisions: retain a single source checkout (logical discovery/freeze extensions only), and do not add a third autonomy-service Skill.
