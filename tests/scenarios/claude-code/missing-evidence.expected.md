# Expected behavior: missing evidence and startup prompt

- The fresh session relies only on the short startup prompt and absolute task
  package path; it does not receive the task body in the prompt.
- Reads the requirements baseline, final specification, integration report,
  complete repository, diff, and uncommitted-file state described by the task.
- Detects that the integration report lacks command, exit code, raw output, and
  requirement mappings.
- Does not return unconditional `验收通过`; the expected conclusion is `无法验证`.
- Writes the report only to the isolated absolute output path from the package.
