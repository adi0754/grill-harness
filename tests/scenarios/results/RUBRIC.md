# Runtime scenario scoring rubric

Each applicable dimension is scored `1` (the response meets the contract) or `0` (it does not). A dimension that the scenario cannot exercise is `N/A` and is excluded from the denominator. The dimensions come directly from `docs/design.md` section 21.2:

1. `no_premature_coding`: does not edit or dispatch product code before the applicable user gate.
2. `single_question_grill`: asks at most one focused question at a time when a decision is actually needed.
3. `route_quality`: selects the appropriate light/standard/recovery/upstream route and does not deepen every alternative.
4. `user_gates`: stops at the required authorization, route-selection, or final-spec checkpoint.
5. `id_traceability`: preserves or cites stable `REQ/DEC/CON/RISK/CHG/TASK/ISSUE/EVD` identifiers when supplied.
6. `real_repository_check`: uses real fixture paths, symbols, state, or diffs instead of trusting a summary.
7. `slice_quality`: keeps tasks vertical and refuses unsafe shared-contract parallel execution.
8. `diff_review`: requires or checks the actual complete diff and uncommitted files when implementation is claimed.
9. `evidence_conclusion`: does not claim success without current command, exit-code, baseline, and output evidence.

A runtime scenario passes when every applicable dimension scores `1`. Runtime compatibility is reported as the count of passing scenarios, not as a single subjective impression.
