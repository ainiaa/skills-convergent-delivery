# Core + Extensions Plan

## Frozen objective

Keep Converge's delivery guarantees while making the default installed and
frozen controller limited to the core delivery path. Autonomy and multi-model
execution remain supported, but are selected explicitly and frozen with the
run that uses them. Inline work creates neither state nor a snapshot.

## Findings being closed

| ID | Problem | Required outcome |
| --- | --- | --- |
| CE-1 | `core`/`extended` snapshots are only an explicit snapshot option; an ordinary persistent state still fingerprints the complete controller. | A new persistent state records the selected extension set and validates only that frozen set. |
| CE-2 | A fixed `extended` profile bundles unrelated optional execution surfaces and tests. | Snapshots use an ordered, closed extension set (`autonomy`, `multimodel`) rather than a catch-all profile. |
| CE-3 | Autonomy and multi-model have no separately discoverable opt-in Skill entry. | The installer installs extension Skills only when their matching option is requested. |
| CE-4 | `codebase-memory-mcp` is accepted as a full-closure graph backend without a verified query contract. | Only CodeGraph can release a full-closure graph gate until a real backend adapter and executable POC exist. |
| CE-5 | The quick check must not repeatedly run the full autonomy trajectory. | Keep the existing default/`--full` split. |

## Design

`controller_snapshot.py` owns one core manifest plus two closed extension
manifests. A caller supplies zero or more known extensions; dependencies are
expanded deterministically, duplicates are rejected, and the descriptor stores
the resulting ordered list. The controller identity uses exactly the same file
set. There is no `core` or `extended` mode.

The first change keeps shared contracts in the core source tree. It moves
discovery and frozen execution boundaries first, without introducing a plugin
loader or changing runner protocol semantics. Physical source extraction is
only justified after the extension boundaries have been exercised in real
installations.

## Reference decision record

| Capability | Reference | Decision | Behaviour test |
| --- | --- | --- | --- |
| Skill packaging and progressive disclosure | OpenAI Skill Creator; Anthropic `skill-creator` | Adopt separate, narrowly triggered Skill folders; do not duplicate generic instructions. | Installer exposes an extension only when requested; core validation succeeds without it. |
| State and recovery | Existing immutable controller snapshot contract | Adopt a frozen extension list in the state/descriptor; do not infer extensions from files at recovery. | Changing an unselected extension preserves core identity; changing a selected one invalidates it. |
| Graph audit | Existing CodeGraph contract | Do not adopt a generic graph-backend abstraction before a real second backend exists. | A `codebase-memory-mcp` label is rejected; CodeGraph evidence remains accepted. |
| Full autonomy evaluation | Existing evaluator | Retain the explicit full trajectory command. | Default check skips it; `--full` and direct catalog evaluation execute it. |

## Execution slices

1. Add failing contract tests for explicit extension manifests, core identity
   isolation, and rejection of the unverified graph backend.
2. Replace profile snapshots with extension manifests and bind non-snapshot
   persistent state identity to the selected extensions.
3. Add `converge-autonomy` and `converge-multimodel` extension Skills and
   installer switches; migrate documentation.
4. Remove the unverified backend claim, update the changelog, and run targeted,
   default, and full trajectory checks.

## Boundaries

No external graph tool is installed by this change. No release, push,
deletion, or managed user installation is performed.
