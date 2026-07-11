---
name: grill-harness
description: Use when starting, continuing, checking, or recovering a stateful software-engineering workflow, or when checking changes in its upstream capabilities.
---

# Grill Harness

## Core rule

Route from verified project state, never conversation memory. Bundled scripts are machine authority; references contain stage logic.

## Entry protocol

Before choosing a route:

Resolve `<grh>` to the absolute path of `scripts/grh.py`, then use its JSON commands:

1. `python3 <grh> identify --project <absolute-project>`
2. `python3 <grh> preflight [--skill-root <installed-skills-root>]`
3. `python3 <grh> status --project <absolute-project> [--workflow <state.yaml>]`
4. When a specific artifact needs checking: `python3 <grh> reconcile --workflow <state.yaml>`

`status` reconciles present artifacts and checks phase gates before returning `next_eligible_phase`. `not_started` plus start intent takes the start route; absence alone is not recovery. Exit `1` means dependency or reconciliation policy blocked progress; exit `2` means input/I/O failure. On either, stop and report the JSON—never infer success. A prior Agent summary is not gate evidence.

## Intent routes

| User intent | Route |
|---|---|
| Start, plan, or shape new work | Load `references/工作流状态机.md` and `references/文档与产物契约.md`; begin at the earliest incomplete pre-implementation phase. |
| Continue, resume, or “pick up where we left off” | Use reconciled persisted state, then enter only the next phase whose prerequisites pass. Load that phase's references before acting. |
| Status, progress, or “what is next?” | Read only. Report project/workflow identity, authoritative phase, gate status, conflicts, and next eligible action. |
| Recover, interrupted, inconsistent, or manually edited workflow | Load `references/工作流状态机.md` and `references/文档与产物契约.md`; preserve conflicting artifacts, stop affected phases, and request the required user decision. Never choose the most complete-looking file as authority. |
| Check upstream skills or dependencies | Load `references/上游适配契约.md`; run `python3 <grh> upstream-check --previous <manifest> --facts <facts> --checked-at <ISO-8601> [--offline]`. Installation, update, or acceptance requires separate user approval. |

## Reference loading

- Alignment through final-spec approval: `references/工作流状态机.md` and `references/文档与产物契约.md`
- Task splitting or implementation: `references/角色任务协议.md`
- Independent assurance or archive: `references/测试与验收.md` and `references/文档与产物契约.md`
- Local role launch: the matching `references/Codex运行时.md` or `references/Claude-Code运行时.md`

Do not copy detailed stage procedures into this router.

## Product-code gate

Before `final_spec_approval` passes for the exact approved artifact version, do not edit product code, dispatch implementation, or create implementation branches/worktrees. In light mode, the merged gate still requires explicit user authorization recorded against the artifact. Repository inspection and workflow-artifact maintenance remain read-only with respect to product code.
