# Expected behavior: upstream change

- Runs the deterministic upstream compatibility command against the two fixture
  inputs.
- Classifies the changed grilling behavior contract as high risk.
- Recommends deferring or adapting and re-running compatibility scenarios.
- Does not install, update, or accept upstream changes.
- Preserves an explicit approval gate for any later update.
