# Task 6 Report — Shared Protocols, README, and Runtime Scenarios

Date: 2026-07-12

## Outcome

Updated the public documentation and reproducible scenario contracts to match the V2 implementation already enforced by Tasks 1–5:

- one Router plus seven thin public entries;
- verified wildcard install syntax `-s '*'` and fail-closed missing-core recovery;
- adaptive requirements radar and analogue comparison before baseline approval;
- three separately approved human gates even in lightweight mode;
- user-selected investigation Agents and no automatic public-entry chaining;
- `grh-plan`, `grh-run`, and `grh-check` stop/isolation boundaries;
- four persisted failure classes, append-only failure manifest, third-attempt recovery, and append-only review convergence;
- read-only knowledge reuse, tentative drafts, project promotion, and a separately approved general-knowledge promotion;
- rejected formal archive before accepted assurance;
- strictly read-only upstream checking with update actions outside the entry.

Added eight V2 scenarios to Router, Codex, and Claude Code definitions:

1. requirement-only scope;
2. non-recommended route selection;
3. review-only;
4. unaccepted archive rejection;
5. third repeated implementation failure;
6. route-failure reselection;
7. knowledge reuse;
8. upstream read-only action boundary.

The new real-model scenarios were not executed. Existing Codex and Claude Code evidence summaries now explicitly mark the additional V2 scenarios as definition-only and unverified; no model pass is claimed.

## Documentation TDD evidence

RED command:

```bash
python3 -m unittest tests.unit.test_templates tests.unit.test_router_scenarios -v
```

Observed RED: 17 tests ran with 2 assertion failures and missing-file errors for all eight new Router scenarios. The failures specifically showed the old README still documented a single entry and merged lightweight gates, while shared references lacked the V2 radar/knowledge/failure contracts.

GREEN command:

```bash
python3 -m unittest tests.unit.test_templates tests.unit.test_router_scenarios tests.unit.test_codex_scenarios tests.unit.test_claude_code_scenarios -v
```

Result: 24 tests passed.

Full unit verification:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Result: 292 tests passed.

Formatting verification:

```bash
git diff --check
```

Result: passed with no output.

## Install verification note

`tests/integration/test_skills_install.sh` was re-run. The local repository discovery and eight-entry `-s '*'` installation completed successfully in the isolated HOME. The later external `mattpocock/skills` clone could not complete during this run because of external GitHub rate/network availability, so this run is not reported as a full integration PASS. The README claim is also backed by the previously committed Task 2 integration evidence and the unchanged executable integration contract.

## Self-review

- Removed stale “single public skill” and “merge lightweight gates” language.
- Distinguished the human-readable radar/archive steps from the twelve machine phases in `state.py`.
- Confirmed documented CLI command names and options against current `grh.py --help`.
- Confirmed all automatic install/update/chaining mentions are prohibitions, not promises.
- Confirmed no personal paths or credentials were added.
- Confirmed no result artifact claims the eight new model scenarios passed.

## Review follow-up

Resolved the post-commit Important and Minor documentation findings:

- failure or unverifiable workflows now explicitly retain only truthful conclusions and cannot complete formal archive; only a confirmed `route_failure` may persist project-level failure facts, without completing `knowledge_archive` or promoting general knowledge;
- the state-machine reference now lists the exact twelve `state.py` phases and places research/prototype work only as optional artifacts inside `design` or `repository_challenge`; optional artifact omission never marks a required machine phase `skipped`.
