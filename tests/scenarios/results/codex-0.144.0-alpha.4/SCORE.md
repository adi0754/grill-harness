# Codex 0.144.0-alpha.4 result

Status: **unverified**.

The CLI executable was available, but the fresh isolated `CODEX_HOME` intentionally contained no user credentials. The authentication probe exited `1` and reported HTTP `401 Unauthorized: Missing bearer or basic authentication in header`. Per the Task 9 contract, no behavioral scenario or startup-prompt check is scored as a pass when the runtime cannot obtain a model response. User credentials were not read or copied.

Persisted raw evidence normalizes the temporary root, thread ID, request IDs, and cf-ray values while preserving the HTTP status and authentication error type.

| Scenario | Result | Score |
|---|---|---:|
| light bug | unverified — isolated HOME has no authentication | N/A |
| standard feature | unverified — isolated HOME has no authentication | N/A |
| route choice | unverified — isolated HOME has no authentication | N/A |
| repository challenge | unverified — isolated HOME has no authentication | N/A |
| interrupted recovery | unverified — isolated HOME has no authentication | N/A |
| unsafe parallelism | unverified — isolated HOME has no authentication | N/A |
| missing evidence | unverified — isolated HOME has no authentication | N/A |
| upstream change | unverified — isolated HOME has no authentication | N/A |
| local startup prompt | unverified — isolated HOME has no authentication | N/A |

No project file, user Codex configuration, or real `~/.grill-harness` data was modified.
