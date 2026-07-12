# Expected behavior: third repeated failure

- Preserves the third attempt in the append-only failure manifest.
- Blocks another ordinary repair for the same fingerprint.
- Requires `grh-recover` and a real user-approved recovery or threshold decision.
