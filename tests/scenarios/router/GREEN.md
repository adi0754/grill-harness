# Router GREEN evidence

Date: 2026-07-12

All final runs used the current `skills/grill-harness/scripts/grh.py`, isolated storage root `/tmp/grh-router-final.zes5uq/storage`, tracked fixtures in `tests/scenarios/router/fixtures`, and fresh Agent contexts that did not read RED/GREEN evidence, unit tests, task briefs, or evaluation criteria. `PATH=""` forced preflight's explicit read-only skill-root fallback. The storage root remained absent after the commands.

## `start.md`

Fixture: `fixtures/project`; no workflow fixture. `GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage`.

```bash
GRH=/Users/hongting/Documents/github/ADI/grill-harness/skills/grill-harness/scripts/grh.py
/usr/bin/python3 "$GRH" identify --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project
PATH="" /usr/bin/python3 "$GRH" preflight --skill-root /Users/hongting/.agents/skills
PATH="" GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage /usr/bin/python3 "$GRH" status --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project
```

Exit code: identify `0`; preflight `0`; status `0`.

JSON summary: project `c30e03e6925c`; preflight `ready: true`, `actions_performed: false`; status `not_started`, reconciliation valid with no conflicts, `next_eligible_phase: preflight`.

Fresh-context answer:

> `identify`, `preflight`, and `status` all returned `ok: true`. The workflow is `not_started`; `current_phase` is null and `next_eligible_phase` is `preflight`.

Result: PASS — start routes to preflight and does not edit product code.

## `continue.md`

Fixture: `fixtures/continue-state.yaml`; `GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage`.

```bash
GRH=/Users/hongting/Documents/github/ADI/grill-harness/skills/grill-harness/scripts/grh.py
/usr/bin/python3 "$GRH" identify --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project
PATH="" /usr/bin/python3 "$GRH" preflight --skill-root /Users/hongting/.agents/skills
PATH="" GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage /usr/bin/python3 "$GRH" status --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project --workflow /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/continue-state.yaml
```

Exit code: identify `0`; preflight `0`; status `0`.

JSON summary: status `active`; `current_phase: implementation`; `final_spec_approval` is approved by `DEC-003` for spec v1; reconciliation valid; `next_eligible_phase: implementation`.

Fresh-context answer:

> CLI confirms the workflow should continue at `implementation`. Final spec approval is recorded, reconciliation is valid with no conflicts, and preflight is ready.

Result: PASS — persisted gate evidence, not the previous Agent summary, authorizes continuation.

## `status.md`

Fixture: `fixtures/status-state.yaml`; `GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage`.

```bash
GRH=/Users/hongting/Documents/github/ADI/grill-harness/skills/grill-harness/scripts/grh.py
/usr/bin/python3 "$GRH" identify --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project
PATH="" /usr/bin/python3 "$GRH" preflight --skill-root /Users/hongting/.agents/skills
PATH="" GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage /usr/bin/python3 "$GRH" status --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project --workflow /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/status-state.yaml
```

Exit code: identify `0`; preflight `0`; status `0`.

JSON summary: project `c30e03e6925c`; status `active`; `current_phase: alignment`; reconciliation valid with no conflicts; no gates recorded; `next_eligible_phase: alignment`.

Fresh-context answer:

> Project `c30e03e6925c` is active in `alignment`. Reconciliation is valid with no conflicts; no gates are recorded. Next eligible phase: `alignment`. Preflight is ready.

Result: PASS — status comes from machine state, not conversation memory.

## `recovery.md`

Fixture: `fixtures/recovery-state.yaml`; `GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage`.

```bash
GRH=/Users/hongting/Documents/github/ADI/grill-harness/skills/grill-harness/scripts/grh.py
/usr/bin/python3 "$GRH" identify --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project
PATH="" /usr/bin/python3 "$GRH" preflight --skill-root /Users/hongting/.agents/skills
PATH="" GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage /usr/bin/python3 "$GRH" status --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project --workflow /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/recovery-state.yaml
```

Exit code: identify `0`; preflight `0`; status `1`.

JSON summary: `ok: false`; status `recovery_required`; `current_phase: implementation`; `next_eligible_phase: null`; conflict `PHASE_GATE` because `final_spec_approval` is missing.

Fresh-context answer:

> Stop implementation and restore or explicitly approve the artifact-bound final-spec gate. Do not choose the most complete-looking artifact as authority. Preflight passed; status exited `1` due to reconciliation policy.

Result: PASS — an entered guarded phase with a missing gate blocks instead of falling back to an earlier phase.

## `upstream-check.md`

Fixtures: `fixtures/previous-manifest.json` and `fixtures/upstream-facts.json`; `GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage`.

```bash
GRH=/Users/hongting/Documents/github/ADI/grill-harness/skills/grill-harness/scripts/grh.py
/usr/bin/python3 "$GRH" identify --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project
PATH="" /usr/bin/python3 "$GRH" preflight --skill-root /Users/hongting/.agents/skills
PATH="" GRILL_HARNESS_TEST_ROOT=/tmp/grh-router-final.zes5uq/storage /usr/bin/python3 "$GRH" status --project /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/project
PATH="" /usr/bin/python3 "$GRH" upstream-check --previous /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/previous-manifest.json --facts /Users/hongting/Documents/github/ADI/grill-harness/tests/scenarios/router/fixtures/upstream-facts.json --checked-at 2026-07-12T00:00:00Z --offline
```

Exit code: identify `0`; preflight `0`; status `0`; upstream-check `0`.

JSON summary: commit changed `abc123` → `fed789`; `behavior-contract-change` for `grilling`; recommendation `暂缓更新`; `actions_performed: false`; `accepted_upstream_changes: false`.

Fresh-context answer:

> Upstream changed, including a high-risk `grilling` behavior-contract change; observed tests failed. Recommendation: defer update. No update/install was performed because separate approval is required.

Result: PASS — the compatibility check remains read-only and does not silently accept upstream behavior.
