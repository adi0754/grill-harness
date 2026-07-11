# Task 9 report: Codex and Claude Code behavior validation

Date: 2026-07-12 (Asia/Shanghai)

## Outcome

Task 9 produced reproducible fresh-context scenario packages and isolated runtime evidence for Codex and Claude Code. Neither runtime is claimed as behaviorally compatible because the required credential-free isolated HOME environments could not authenticate before model/Skill execution.

| Runtime | CLI | Isolated result | Behavioral score | Startup prompt |
|---|---|---|---|---|
| Codex | `codex-cli 0.144.0-alpha.4` | exit `1`; HTTP 401, missing bearer/basic authentication | 8 scenarios unverified | unverified; no model response |
| Claude Code | `2.1.197` | auth `loggedIn:false`, `authMethod:none`; 8 calls exit `1` with `Not logged in · Please run /login` | 8 scenarios unverified | unverified; report not written |

The status follows the design rule: an installed CLI is not a passed runtime. No rubric dimension was awarded when authentication prevented observable behavior.

## Scenario coverage

Equivalent definitions exist for:

1. lightweight bug;
2. standard cross-module feature;
3. route choice;
4. repository challenge;
5. interrupted recovery;
6. unsafe parallelism;
7. missing evidence;
8. upstream behavior change.

The shared rubric scores the nine design dimensions: premature coding, one-question Grill, route quality, user gates, stable-ID traceability, real repository inspection, vertical-slice/parallel safety, complete diff review, and evidence-backed conclusion.

## Isolation and safety

- Every runner creates a temporary HOME, runtime configuration directory, Skill copy, and `GRILL_HARNESS_TEST_ROOT`.
- User credentials are not read or copied.
- Claude Code uses a distinct read-only Git fixture for each scenario and disables session persistence; recorded fixture `git status` is empty after every call.
- Codex uses the read-only sandbox for behavioral scenarios. The startup-prompt path would grant write access only to a temporary report directory after a successful auth probe.
- Neither runner touches user global configuration or the real `~/.grill-harness`.
- No dependency was installed.
- The Codex runner does not create placeholder upstream Skills; a future authenticated behavioral rerun must provision the real required capabilities inside its isolated Skill directory.

## Local startup prompt

Both suites construct an absolute task-package path, absolute fixture-project path, and isolated absolute report path using the short local startup contract from `references/角色任务协议.md`. Codex authentication failed before the startup call could run. Claude Code exited before reading the task package, so the expected isolated report was not written. Both are therefore explicitly unverified, not failed behavioral assertions.

## Evidence locations

- `tests/scenarios/codex/`: Codex scenario definitions, fixture, and isolated runner.
- `tests/scenarios/claude-code/`: Claude Code prompts, expected behavior, fixture, and isolated runner.
- `tests/scenarios/results/RUBRIC.md`: shared scoring contract.
- `tests/scenarios/results/codex-0.144.0-alpha.4/`: Codex version, auth probe, per-scenario unverified markers, and score.
- `tests/scenarios/results/claude-code/`: per-run version/auth/command/prompt/task-package/Git/stdout/stderr/result evidence and summary.

## Transferable defects

No transferable Grill Harness Skill or deterministic-script defect could be established because neither runtime reached Skill execution. No product Skill behavior was changed.

## Reproduction commands

```sh
tests/scenarios/codex/run.sh tests/scenarios/results/codex-0.144.0-alpha.4
python3 tests/scenarios/claude-code/run.py
python3 -m unittest discover -s tests -v
git diff --check
```

Re-running the runtime commands in a credential-free isolated HOME is expected to preserve the explicit unverified result. First-class behavioral scoring requires separately provisioned credentials that are valid inside an isolated HOME; this task did not copy or reuse user credentials.
