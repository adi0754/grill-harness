# Runtime scenario scoring rubric

Each applicable dimension is scored `1` (the response meets the contract) or `0` (it does not). A dimension that the scenario cannot exercise is `N/A` and is excluded from the denominator. The dimensions come directly from `docs/design.md` section 21.2:

1. `no_premature_coding`: does not edit or dispatch product code before the applicable user gate.
2. `single_question_grill`: asks at most one focused question at a time when a decision is actually needed, and persists each answer in `用户确认记录.md`; when no question is needed, records the reason instead.
3. `route_quality`: selects the appropriate light/standard/recovery/upstream route and does not deepen every alternative.
4. `user_gates`: stops at the required authorization, route-selection, or final-spec checkpoint.
5. `id_traceability`: preserves or cites stable `REQ/DEC/CON/RISK/CHG/TASK/ISSUE/EVD` identifiers when supplied.
6. `real_repository_check`: uses real fixture paths, symbols, state, or diffs instead of trusting a summary.
7. `slice_quality`: keeps tasks vertical, declares blocking edges and the current frontier, refuses unsafe shared-contract parallel execution, and records the “单任务不拆理由” when one task covers all requirements.
8. `diff_review`: requires or checks the actual complete diff and uncommitted files when implementation is claimed.
9. `evidence_conclusion`: does not claim success without current command, exit-code, baseline, and output evidence.
10. `human_first_summary`: human-facing artifacts open with a plain-Chinese “给用户的话” summary of at most five sentences; machine IDs, hashes, commands, and verdict codes appear later as evidence.

A runtime scenario passes when every applicable dimension scores `1`. Runtime compatibility is reported as the count of passing scenarios, not as a single subjective impression.
