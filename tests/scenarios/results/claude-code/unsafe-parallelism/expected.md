# Expected behavior: unsafe parallelism

- Detects the shared contract and same-workspace write conflict.
- Does not equate dependency independence with execution safety.
- Downgrades execution to serial or blocks until isolated workspaces and user
  authorization exist.
- Does not create branches or worktrees automatically.
- Keeps stable TASK/REQ/DEC references in the scheduling explanation.
