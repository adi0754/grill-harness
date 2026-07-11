# Grill Harness Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Use fresh reviewers for scenario evaluation. Do not skip the RED baseline for the Skill itself.

**Goal:** Build and publish a single-entry `grill-harness` Skill that installs through skills.sh, stores all runtime data under `~/.grill-harness/`, supports Codex and Claude Code, composes required Matt Pocock capabilities, and produces local role task prompts for user-selected agents.

**Architecture:** Keep the installed Skill thin: `SKILL.md` routes a versioned workflow state machine and loads focused references. Deterministic Python standard-library scripts own storage, validation, DAG/frontier calculation, dependency discovery, upstream comparison, atomic writes, and migrations. Runtime documents remain outside project repositories.

**Tech Stack:** Agent Skills Markdown, Python 3 standard library, JSON-compatible YAML files, shell/skills.sh/GitHub CLI integration, `unittest`, Git.

## Global Constraints

- Only one public Skill: `grill-harness`.
- Runtime state and documents only under `~/.grill-harness/`.
- Do not write Grill Harness state or documents into target project repositories.
- Human-facing runtime directories and documents use concise Chinese names.
- Machine protocol files use stable names: `state.yaml`, `artifacts.yaml`, `tasks.yaml`, `evidence.yaml`.
- Treat machine `.yaml` files as the JSON-compatible subset of YAML so Python can parse them without third-party libraries.
- First-class runtime validation: Codex and Claude Code.
- Required upstream capabilities: `grilling`, `domain-modeling`, `codebase-design`.
- Do not copy upstream Skill text or silently replace missing required capabilities.
- Do not automatically install or update third-party Skills.
- Do not automatically choose or launch formal implementer, reviewer, fixer, integrator, or verifier agents.
- Generate local task packages and short local startup prompts; the user chooses the model and Agent.
- Default GitHub repository visibility is private.
- Create the local repository only at `/Users/hongting/Documents/github/ADI/grill-harness`.
- Never overwrite an existing GitHub repository or local directory.

---

### Task 1: Create the repository safely and capture the baseline

**Files:**
- Create: repository root at `/Users/hongting/Documents/github/ADI/grill-harness`
- Create: `docs/design.md`
- Create: `tests/baseline/README.md`

**Interfaces:**
- Consumes: approved design specification
- Produces: private GitHub repository, local Git checkout, immutable design copy, RED baseline evidence

- [ ] Verify `gh auth status` and derive the active GitHub login with `gh api user --jq .login`.
- [ ] Set `owner="$(gh api user --jq .login)"`, then check whether `$owner/grill-harness` already exists. If it exists, stop and report the collision; do not reuse or delete it.
- [ ] Confirm `/Users/hongting/Documents/github/ADI` exists and `/Users/hongting/Documents/github/ADI/grill-harness` does not exist.
- [ ] Create a private repository with GitHub CLI, clone it exactly to `/Users/hongting/Documents/github/ADI/grill-harness`, and configure `origin`.
- [ ] Copy the approved design specification to `docs/design.md` without changing its decisions.
- [ ] Create at least four pressure scenarios before writing `SKILL.md`: premature coding, skipping route approval, trusting an implementer summary, and claiming completion without evidence.
- [ ] Run those scenarios without Grill Harness using fresh Agent contexts where available. Record exact observed failures in `tests/baseline/README.md`.
- [ ] Commit with a message such as `docs: establish grill harness design and baseline` and push the private default branch.

### Task 2: Scaffold the portable Skill package

**Files:**
- Create: `README.md`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `skills/grill-harness/SKILL.md`
- Create: `skills/grill-harness/agents/openai.yaml`
- Create: `skills/grill-harness/references/*.md`
- Create: `skills/grill-harness/scripts/*.py`
- Create: `skills/grill-harness/assets/templates/*`

**Interfaces:**
- Consumes: current Agent Skills specification and local skill-creator tooling
- Produces: skills.sh-discoverable single Skill package

- [ ] Inspect the current Codex and skills.sh Skill specifications and at least two installed working examples.
- [ ] Use the current official Skill initializer when compatible; otherwise create the same required structure manually and document why.
- [ ] Keep frontmatter to the portable common subset: `name` and `description`.
- [ ] Set the name exactly to `grill-harness`.
- [ ] Write the description as trigger conditions rather than a workflow summary.
- [ ] Generate `agents/openai.yaml` using the current official helper and validate it against `SKILL.md`.
- [ ] Keep the Skill folder free of README, changelog, and installation-guide files; put distribution documentation at repository root.
- [ ] Commit and push the scaffold.

### Task 3: Implement the user-level storage and project identity layer

**Files:**
- Create: `skills/grill-harness/scripts/common.py`
- Create: `skills/grill-harness/scripts/state.py`
- Create: `tests/unit/test_storage.py`
- Create: `tests/unit/test_project_identity.py`
- Create: `tests/unit/test_atomic_writes.py`

**Interfaces:**
- Produces: storage-root resolution, Chinese directory creation, project fingerprints, workflow IDs, atomic JSON-compatible YAML reads/writes

- [ ] Write failing tests for default root resolution, explicit test root override, required Chinese directories, project ID stability, same-name repository separation, repository relocation candidates, non-Git projects, multiple workflow isolation, and interrupted writes.
- [ ] Run `python3 -m unittest` for these files and confirm the intended failures.
- [ ] Implement storage root resolution with a test-only environment override and production default `~/.grill-harness/`.
- [ ] Implement Git project fingerprints from normalized path, normalized remote, and stable repository history facts without hashing private file contents.
- [ ] Implement human-readable project and workflow directory names with short stable IDs.
- [ ] Implement atomic writes using a temporary sibling file, fsync where supported, and rename/replace.
- [ ] Implement backups before destructive schema migration.
- [ ] Run tests and commit the storage layer.

### Task 4: Implement the workflow state machine and artifact contracts

**Files:**
- Modify: `skills/grill-harness/scripts/state.py`
- Create: `skills/grill-harness/scripts/validate.py`
- Create: `tests/unit/test_state_machine.py`
- Create: `tests/unit/test_ledger.py`
- Create: `tests/unit/test_artifacts.py`
- Create: `tests/fixtures/workflows/*`

**Interfaces:**
- Produces: legal transitions, three human gates, versioned ledger records, artifact reconciliation, stale/superseded propagation

- [ ] Write failing tests for every legal and illegal transition across `pending`, `in_progress`, `needs_user`, `blocked`, `completed`, `stale`, `superseded`, `skipped`, `failed`, and `cancelled`.
- [ ] Write failing tests proving that completed phases require artifacts and evidence.
- [ ] Write failing tests for stable `REQ`, `DEC`, `CON`, `RISK`, `CHG`, `TASK`, `ISSUE`, and `EVD` IDs and version increments.
- [ ] Write failing tests that a changed decision marks affected specs, tasks, and evidence stale.
- [ ] Implement the state and artifact validators without silently repairing contradictions.
- [ ] Implement reconciliation reports that explain the conflict and required recovery action in Chinese.
- [ ] Run tests and commit.

### Task 5: Implement task graphs, conflict analysis, and evidence validation

**Files:**
- Create: `skills/grill-harness/scripts/task_graph.py`
- Modify: `skills/grill-harness/scripts/validate.py`
- Create: `tests/unit/test_task_graph.py`
- Create: `tests/unit/test_conflicts.py`
- Create: `tests/unit/test_evidence.py`

**Interfaces:**
- Produces: acyclic DAG validation, Frontier calculation, conservative parallel candidates, shared-contract conflict detection, evidence validity

- [ ] Write failing tests for DAG cycles, blockers, Frontier changes, shared paths, shared contracts, migrations, generated files, and independent worktrees.
- [ ] Write failing tests proving tasks without distinct worktrees cannot be executable in parallel.
- [ ] Write failing tests for evidence command, working directory, exit code, baseline, producer, reproducibility, and staleness.
- [ ] Implement deterministic graph and conflict functions with machine-readable and Chinese human-readable results.
- [ ] Run tests and commit.

### Task 6: Implement dependency preflight and upstream compatibility tracking

**Files:**
- Create: `skills/grill-harness/scripts/preflight.py`
- Create: `skills/grill-harness/scripts/upstream_check.py`
- Create: `skills/grill-harness/references/上游适配契约.md`
- Create: `tests/unit/test_preflight.py`
- Create: `tests/unit/test_upstream_check.py`
- Create: `tests/fixtures/upstream/*`

**Interfaces:**
- Consumes: `npx skills list --json`, known Skill roots, metadata, upstream Git facts
- Produces: capability status, install guidance, pinned manifest, classified compatibility report

- [ ] Write failing tests for global/project installs, symlinks, missing CLI, missing capabilities, optional capabilities, stale metadata, offline mode, renamed upstream files, and behavior-contract changes.
- [ ] Implement discovery using CLI JSON first and filesystem/metadata verification second.
- [ ] Treat `grilling`, `domain-modeling`, and `codebase-design` as required capabilities.
- [ ] Track `grill-with-docs` as a compatibility reference, not a callable dependency.
- [ ] Generate install/update commands from the current CLI rather than fixed historical syntax.
- [ ] Implement upstream manifest fields for repository, ref, commit, timestamps, license, source paths, hashes, behavior contracts, local differences, risks, and last test results.
- [ ] Never install, update, overwrite, or accept upstream changes automatically.
- [ ] Run tests and commit.

### Task 7: Implement templates and focused workflow references

**Files:**
- Create: `skills/grill-harness/references/工作流状态机.md`
- Create: `skills/grill-harness/references/文档与产物契约.md`
- Create: `skills/grill-harness/references/角色任务协议.md`
- Create: `skills/grill-harness/references/Codex运行时.md`
- Create: `skills/grill-harness/references/Claude-Code运行时.md`
- Create: `skills/grill-harness/references/测试与验收.md`
- Create: templates for baseline, ledger, route card, repository challenge, spec, task graph, implementation, review, fix, integration, verification, and lessons
- Create: `tests/unit/test_templates.py`

**Interfaces:**
- Produces: Chinese human documents and local role prompts that reference stable machine contracts

- [ ] Write tests for required template fields, stable IDs, local absolute task paths, output paths, stop conditions, and absence of full chat history.
- [ ] Encode lightweight, standard, and Wayfinding mode differences.
- [ ] Encode the three human gates and route-card stop behavior.
- [ ] Encode repository challenge conclusions and two-axis review.
- [ ] Encode short local startup prompts; do not create web/portable prompt templates.
- [ ] Run tests and commit.

### Task 8: Write the thin router Skill

**Files:**
- Modify: `skills/grill-harness/SKILL.md`
- Create: `tests/scenarios/router/*`

**Interfaces:**
- Consumes: user intent, current project, persisted state, deterministic script results
- Produces: correct phase routing and reference loading without duplicating stage logic

- [ ] Re-run the baseline pressure scenarios without the new Skill and retain the RED evidence.
- [ ] Write the minimum router instructions that directly address observed failures.
- [ ] Require preflight, artifact reconciliation, and phase prerequisites before routing.
- [ ] Route natural-language requests for start, continue, status, recovery, and upstream check.
- [ ] Prohibit product-code edits before required user gates.
- [ ] Keep detailed stage content in references and keep `SKILL.md` under the current recommended size.
- [ ] Run scenario tests with the Skill present and record GREEN results.
- [ ] Add counters only for observed loopholes, then re-run scenarios.
- [ ] Commit.

### Task 9: Validate Codex and Claude Code behavior

**Files:**
- Create: `tests/scenarios/codex/*`
- Create: `tests/scenarios/claude-code/*`
- Create: `tests/scenarios/results/*`

**Interfaces:**
- Produces: first-class compatibility evidence or explicit unverified limitations

- [ ] Run equivalent fresh-context scenarios in Codex and Claude Code for lightweight bug, standard feature, route choice, repository challenge, interrupted recovery, unsafe parallelism, missing evidence, and upstream change.
- [ ] Score each run against the rubric in the design specification.
- [ ] Verify local startup prompts can be used from a new session to read the task package and write the required report.
- [ ] Do not claim a runtime passed if its CLI or environment is unavailable; mark it unverified with exact reason.
- [ ] Fix transferable Skill or script defects and re-run affected scenarios.
- [ ] Commit evidence and fixes.

### Task 10: Validate skills.sh installation and write distribution documentation

**Files:**
- Modify: `README.md`
- Modify: `LICENSE`
- Create: `tests/integration/test_skills_install.sh`
- Create: `tests/integration/test_runtime_data.sh`

**Interfaces:**
- Produces: verified install/update commands and accurate user documentation

- [ ] Test repository discovery with current skills.sh.
- [ ] Test isolated installation for Codex and Claude Code without mutating the user's existing Skill directories.
- [ ] Verify installation does not create runtime project data.
- [ ] Verify first use creates runtime data only under the configured test equivalent of `~/.grill-harness/`.
- [ ] Verify uninstall/update does not delete or overwrite user workflow data.
- [ ] Write only actually verified installation, dependency, update, status, recovery, and upstream-check commands.
- [ ] Include concise Chinese examples and clearly label unverified behavior.
- [ ] Commit.

### Task 11: Final verification, review, and publication

**Files:**
- Review all repository files
- Update: `README.md` and test result summaries only if verification requires it

**Interfaces:**
- Produces: pushed private repository and evidence-backed final report

- [ ] Run metadata validation, all unit tests, scenario checks, skills.sh integration tests, secret scanning, and `git diff` review.
- [ ] Use an independent reviewer to compare the repository against `docs/design.md` along Standards and Spec axes.
- [ ] Fix confirmed findings and re-run relevant tests.
- [ ] Confirm no runtime files were written into fixture project repositories except explicitly isolated test artifacts.
- [ ] Confirm no credentials, tokens, cookies, or private environment dumps are committed.
- [ ] Commit final changes and push the private repository.
- [ ] Report repository URL, commit SHA, verified installation commands, actual test commands and exit status, limitations, and any item marked unverified.
- [ ] Do not make the repository public, create a release, or publish to a marketplace without separate user authorization.
