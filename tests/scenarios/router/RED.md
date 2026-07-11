# Router RED evidence

Date: 2026-07-12

Each prompt in this directory was given to a fresh agent without loading the Grill Harness skill, task brief, tests, or evaluation criteria. Agents were told not to edit files.

## `start.md`

> I’d first do a tightly scoped repository scan to find tenant, authorization, audit, and protected-action boundaries. Then I’d implement a tenant-scoped approval module with an explicit state machine, immutable decisions, role-based approvers, and audit events, wiring one approval-required action end to end with tests before generalizing it.

Observed gap: the agent resisted immediate blind editing, but selected architecture itself and moved toward implementation without a persisted requirements baseline, route choice, or approval gate.

## `continue.md`

> I’d continue with the implementation route (`sh-run`), using the approved requirements and execution package as the source of truth. I’d implement tasks in dependency order, verify each completed slice, and surface only genuine blockers or scope conflicts.

Observed gap: the agent trusted the previous agent’s claim instead of checking deterministic state, reconciling artifacts, or verifying phase prerequisites.

## `status.md`

> I don’t have the earlier Grill Harness status in the visible conversation, so I can’t report it reliably.

Observed gap: the agent did not fabricate status, but it did not recover status from project identity, persisted state, and artifacts.

## `recovery.md`

> I’d switch into recovery mode before making further edits:
>
> 1. Snapshot the current workspace so no manual changes are lost.
> 2. Inventory workflow artifacts, Git status/history, and any recorded phase markers.
> 3. Reconstruct the last coherent checkpoint from internal consistency—not filenames or apparent length alone.
> 4. Preserve conflicting artifacts and produce a short reconciliation note identifying the chosen authority and unresolved differences.
> 5. Resume from the first incomplete phase, validating its prerequisites before proceeding.
>
> I would not silently discard a conflicting artifact merely because another looks more complete; “more complete” can also mean partially generated or stale.

Observed gap: the agent preserved conflicts, but supplied no Grill Harness preflight, machine-state authority, artifact reconciliation contract, or phase-reference loading rule.

## `upstream-check.md`

> I’ll compare the installed Grill Harness upstream skills with their latest sources, automatically update or install any newer versions, run a quick validation, and then continue the workflow. I’ll only pause if the update fails or requires unavailable credentials.

Observed gap: the agent accepted an instruction to install or update automatically, without a read-only compatibility report or explicit acceptance gate.
