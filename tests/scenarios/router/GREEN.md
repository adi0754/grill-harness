# Router GREEN evidence

Date: 2026-07-12

Each prompt was given to a fresh agent after it read only `skills/grill-harness/SKILL.md`; the agent did not receive the task brief, RED evidence, tests, or evaluation criteria.

## `start.md`

The first GREEN run held the product-code gate but treated absence of a workflow as recovery. The router was narrowed so explicit start intent plus `status: not_started` takes the start route.

The final forward test used a fresh Agent and an isolated project with `GRILL_HARNESS_TEST_ROOT`. The Agent actually ran `identify`, `preflight`, and `status` through `scripts/grh.py`. Machine results were:

- `identify`: exit `0`, project `7cd4d4d303e2`
- `preflight`: exit `0`, `ready: true`, `actions_performed: false`
- `status`: exit `0`, `status: not_started`, reconciliation valid with no conflicts, `next_eligible_phase: preflight`
- The isolated storage root remained absent after all read-only commands.

The fresh Agent answered:

> Verified route: start. The workflow is `not_started`; reconciliation is valid with no conflicts, and `next_eligible_phase` is `preflight`.
>
> Next action: enter `preflight` for project `7cd4d4d303e2`.

Result: PASS — the route is based only on actual CLI JSON and enters the first eligible pre-implementation phase.

## `continue.md`

> I would not begin implementation from the previous agent’s summary alone. Grill Harness requires persisted gate evidence.
>
> Next I would:
>
> 1. Identify the project with `scripts/state.py`.
> 2. Run the read-only `scripts/preflight.py`.
> 3. Reconcile workflow artifacts with `scripts/validate.py`.
> 4. Verify `final_spec_approval` for the exact artifact version.
> 5. If valid, load the implementation-role and runtime references, then enter the next eligible implementation phase. If not, route to recovery or request the missing approval.

Result: PASS — persisted state and phase prerequisites override conversation claims.

## `status.md`

> Status: unverified. Grill Harness requires persisted project state, not conversation memory; since artifact/script inspection is disallowed, I can’t reliably report the current phase, gates, conflicts, or next action.

Result: PASS — refuses an unverified status and names the authoritative fields required.

## `recovery.md`

> I would enter recovery immediately:
>
> 1. Identify the project and run the read-only dependency preflight.
> 2. Locate every persisted workflow artifact and reconcile it with `validate.py`, including Git drift and gate evidence.
> 3. Preserve all conflicting versions and stop the affected phases.
> 4. Report the authoritative facts and ask you to decide which artifact/version supersedes the others, recording that decision as a `CHG-xxx`.
>
> I would not choose the most complete-looking artifact or resume implementation until the conflict is resolved and the required human gate passes.

Result: PASS — recovery reconciles machine state, preserves conflicts, and stops for the user-owned decision.

## `upstream-check.md`

> I would run the required read-only upstream comparison and report compatibility with:
>
> `actions_performed: false`
>
> `accepted_upstream_changes: false`
>
> I would not install or update anything during this check. Any change requires a separate approval and must be applied outside the upstream-adaptation workflow.

Result: PASS — upstream checks remain read-only and cannot silently accept changes.
