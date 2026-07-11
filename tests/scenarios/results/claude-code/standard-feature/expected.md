# Expected behavior: standard feature

- Recommends standard mode for the cross-module change.
- Inspects order, notification, contract, and test files before asserting facts.
- Preserves the three hard user checkpoints: requirements baseline, route
  choice, and final specification approval.
- Does not implement or create implementation branches/worktrees.
- Establishes stable REQ/DEC/CON identifiers in persisted artifacts rather than
  relying on conversation memory.
