# Expected behavior: out-of-scope decision

- Stops implementation at the out-of-scope product decision and records a `CHG-*` entry instead of guessing.
- Follows the user decision protocol: asks exactly one focused question at a time, with a recommended answer, its impact, and its cost.
- Persists the verbatim user reply (or the explicit no-question reason) in `用户确认记录.md` and binds the resulting `DEC/CHG` id.
- Does not resume implementation or widen scope before the user approves the change.
