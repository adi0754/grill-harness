# Claude Code fresh-context scenarios

These scenarios validate the first-class Claude Code runtime target without
touching the user's real Claude configuration or `~/.grill-harness` data.

`run.py` creates a new temporary root for every scenario, with:

- an isolated `HOME` and `CLAUDE_CONFIG_DIR`;
- a copied Grill Harness Skill under the temporary Claude Skill directory;
- a fresh Git repository copied from `fixtures/project` and made read-only;
- disabled session persistence and a distinct non-interactive Claude process;
- raw stdout, stderr, environment, command, Git baseline, and rubric evidence.

Run all scenarios from the repository root:

```bash
python3 tests/scenarios/claude-code/run.py
```

The runner deliberately does not copy OAuth credentials from the real Claude
home. If the isolated runtime is not authenticated, every behavioral result is
recorded as `未验证` with the exact CLI error. This is preferable to silently
falling back to user-global state.

Claude and Git child processes receive a minimal environment allowlist rather
than a copy of the parent environment. Persisted results normalize random temp
roots, session/thread IDs, UUIDs, request IDs, and cf-ray values while keeping
the authentication error type and exit evidence. Repository and fixture paths
are persisted only as `<REPO_ROOT>` and `<FIXTURE_ROOT>` placeholders.

The sixteen equivalent contexts are:

1. `light-bug`
2. `standard-feature`
3. `route-choice`
4. `repository-challenge`
5. `interrupted-recovery`
6. `unsafe-parallelism`
7. `missing-evidence`
8. `upstream-change`
9. `requirement-only-scope`
10. `non-recommended-route`
11. `review-only`
12. `unaccepted-archive`
13. `third-repeated-failure`
14. `route-failure-reselection`
15. `knowledge-reuse`
16. `upstream-read-only`

`missing-evidence` also exercises the local startup-prompt contract. Its prompt
contains only the short role-launch instruction and an absolute generated task
package path. A successful runtime must read that package and write the report
to the package's isolated absolute output path.
