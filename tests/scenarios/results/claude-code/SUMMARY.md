# Claude Code runtime validation summary

Generated: 2026-07-11T20:21:41.442616+00:00

All eight invocations used a distinct isolated HOME, Skill copy, read-only fixture Git repository, and disabled session persistence.
The runner did not copy credentials or touch the real `~/.grill-harness`.
Persisted evidence uses stable placeholders for temporary roots, session IDs, UUIDs, request IDs, and cf-ray values; authentication status and exit evidence remain intact.

| Scenario | CLI exit | Auth exit | Report written | Conclusion |
|---|---:|---:|---|---|
| light-bug | 1 | 1 | no | 未验证 |
| standard-feature | 1 | 1 | no | 未验证 |
| route-choice | 1 | 1 | no | 未验证 |
| repository-challenge | 1 | 1 | no | 未验证 |
| interrupted-recovery | 1 | 1 | no | 未验证 |
| unsafe-parallelism | 1 | 1 | no | 未验证 |
| missing-evidence | 1 | 1 | no | 未验证 |
| upstream-change | 1 | 1 | no | 未验证 |

Exact blocker: the isolated Claude configuration reports `{"loggedIn": false, "authMethod": "none"}` and every non-interactive call exits `1` with `Not logged in · Please run /login` before model or Skill execution.

Therefore no Claude Code behavioral scenario, including the local startup-prompt report write, is claimed as passed. The scenario definitions and runner remain reproducible in an authenticated isolated HOME.
