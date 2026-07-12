# Grill Harness 多入口升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单入口 Grill Harness 升级为一个兜底 Router、七个人类意图薄入口和单一共享内核，并实现自适应需求雷达、可验证知识闭环及失败收敛机制。

**Architecture:** 十二个内部阶段、三个用户门禁和现有持久化状态继续由主 `grill-harness` 内核负责；公开入口是一次请求的权限边界，不写入持久状态。新增独立策略模块负责入口资格、需求雷达、知识记录和失败分类，所有运行时写入仍限制在 `~/.grill-harness/`。

**Tech Stack:** Agent Skills Markdown、Python 3 标准库、JSON-compatible YAML、skills.sh、Codex、Claude Code、`unittest`、Shell、Git。

## Global Constraints

- 公开 Skills 固定为：`grill-harness`、`grh-start`、`grh-plan`、`grh-run`、`grh-check`、`grh-recover`、`grh-learn`、`grh-upstream-check`。
- 子入口只声明触发条件、范围、禁止事项和停止点；不得复制状态机、模板、脚本或阶段协议。
- 入口调用不能绕过十二阶段、三个分别绑定真实产物版本的人工门禁、Git 基线或证据规则。
- 一个入口结束后只能建议下一入口，不能自动串联或自动换路线。
- 所有运行时状态、过程产物、最终产物和知识只写入 `~/.grill-harness/`；目标产品仓库不保存 Harness 文件。
- 用户决定独立调查、实施、审查、修复、集成和验收使用哪个模型或 Agent。
- `grh-upstream-check` 只读；安装或更新发生在入口外。
- 正式知识归档要求独立最终验收通过并获得用户知识变更确认；路线失败例外只能提前写项目级失败事实。
- 不新增第三方 Python 依赖，不自动安装或更新第三方 Skill。
- 所有行为变更先写失败测试并观察 RED，再写最小实现并观察 GREEN。

---

### Task 1: 建立入口—内核契约与只读资格检查

**Files:**
- Create: `skills/grill-harness/scripts/entry_contract.py`
- Create: `skills/grill-harness/references/入口内核契约.json`
- Modify: `skills/grill-harness/scripts/grh.py`
- Test: `tests/unit/test_entry_contract.py`
- Test: `tests/unit/test_grh_cli.py`

**Interfaces:**
- Produces: `ENTRY_CORE_CONTRACT_VERSION`, `PUBLIC_ENTRIES`, `get_entry_contract()`, `evaluate_entry_request()`, `entry_control_summary()`。
- Produces CLI: `grh.py entry-check --entry NAME --project PATH [--workflow PATH] [--requested-scope VALUE]`。
- Consumes existing status/reconcile output and never mutates workflow state。

- [ ] Write RED tests proving all eight entries exist, share one contract version, narrow scope cannot expand permissions, `grh-run` requires `final_spec_approval`, `grh-check` cannot switch routes, `grh-upstream-check` cannot install/update, and every decision has `will_auto_route: false`.
- [ ] Run `python3 -m unittest tests.unit.test_entry_contract -v`; expect import failure because `entry_contract.py` does not exist.
- [ ] Implement `PUBLIC_ENTRIES` with `kind`, `allowed_phases`, `required_gates`, `allowed_operations`, `forbidden_operations`, `stop_boundary`, `next_entry_suggestions`, `supports_read_only`, `may_initialize`, `may_write_runtime`, `may_write_product`, and `may_archive_knowledge`.
- [ ] Implement `evaluate_entry_request(entry_name, workflow, reconciliation, requested_scope=())` as a pure function returning `eligible`, `reason_code`, `missing_prerequisites`, allowed/forbidden scope, `recommended_entry`, and `will_auto_route: false`.
- [ ] Add process-level RED tests for `entry-check`: `not_started + grh-start` eligible; `not_started + grh-run` exit 1; spec unapproved rejects run; review-only scope excludes final acceptance; no call initializes or transitions state.
- [ ] Implement `_entry_check()` in `grh.py`: identify, preflight, status/reconcile, evaluate, emit control summary. Policy blocks exit 1; malformed input/contracts exit 2.
- [ ] Run `python3 -m unittest tests.unit.test_entry_contract tests.unit.test_grh_cli tests.unit.test_state_machine -v`; expect PASS and unchanged twelve-phase ordering.
- [ ] Commit `feat: add human-controlled entry contracts`.

### Task 2: 发布七个薄入口并验证完整安装

**Files:**
- Create: `skills/grh-{start,plan,run,check,recover,learn,upstream-check}/SKILL.md`
- Create: corresponding `agents/openai.yaml`
- Modify: `skills/grill-harness/SKILL.md`
- Modify: `skills/grill-harness/scripts/preflight.py`
- Modify: `tests/unit/test_preflight.py`
- Modify: `tests/integration/test_skills_install.sh`

**Interfaces:**
- Produces skills.sh-discoverable Router plus seven entries。
- Produces `verify_public_entries()` and `harness_installation` without changing existing `ready` dependency semantics。

- [ ] Write RED tests for complete/incomplete installation, wrong frontmatter names, missing core, incompatible contract, mixed CLI/filesystem discovery, and `actions_performed: false`.
- [ ] Run `python3 -m unittest tests.unit.test_preflight -v`; expect failures for missing harness installation checks.
- [ ] Extend `run_preflight(..., check_harness_entries=False, invoking_entry=None)` with `entry_ready`, `overall_ready`, missing entries, core path and contract compatibility.
- [ ] Create each thin Skill with only trigger conditions, allowed/forbidden scope, stop boundary, main-core discovery, `entry-check`, and fail-closed behavior. Do not assume `../grill-harness`.
- [ ] Update Router to map natural language to entries; explicit user entry wins but state eligibility still applies. Remove all “only one public Skill” claims.
- [ ] Update integration test to discover all eight entries and test isolated Codex/Claude Code install. First test `-s '*'`; if current CLI rejects it, verify an explicit full list and document that fact.
- [ ] Add isolated incomplete-install test: install only `grh-learn`, verify core-missing guidance and no `~/.grill-harness/` creation.
- [ ] Run `python3 -m unittest tests.unit.test_preflight tests.unit.test_entry_contract -v` and `tests/integration/test_skills_install.sh`; expect PASS.
- [ ] Commit `feat: publish human intent workflow entries`.

### Task 3: 实现自适应需求雷达与相似实现对照

**Files:**
- Create: `skills/grill-harness/scripts/requirements_radar.py`
- Modify: `skills/grill-harness/scripts/state.py`
- Modify: `skills/grill-harness/scripts/workflow_ops.py`
- Create templates: `需求雷达.md`, `问题与发现.yaml`, `相似实现对照.md`, `需求调查任务.md`
- Modify: `skills/grill-harness/assets/templates/需求基线.md`
- Test: `tests/unit/test_requirements_radar.py`
- Modify: `tests/unit/test_workflow_ops.py`, `tests/unit/test_templates.py`, `tests/unit/test_ledger.py`

**Interfaces:**
- Produces: `validate_radar_record()`, `classify_escalation()`, `unresolved_baseline_blockers()`, `validate_analogue_comparison()`, `traceability_report()`。
- Adds `RAD-xxx` as stable ledger records and blocks requirements approval while baseline blockers remain open。

- [ ] Write RED tests for all five categories, low/medium/high escalation, user-controlled investigation, unresolved blockers, cross-artifact traceability, and analogue comparison fields.
- [ ] Assert analogue candidates require path/symbol, similarities, differences, reusable parts, non-reuse reasons, shared contracts, reusable tests and new behavior; “not found” requires search scope and evidence.
- [ ] Run `python3 -m unittest tests.unit.test_requirements_radar -v`; expect module import failure.
- [ ] Implement pure radar validators and add `RAD` to `state.LEDGER_RECORD_TYPES`; update ledger fixtures/templates.
- [ ] Before `approve_gate(requirements_baseline)` writes, reject current open records with `blocking_level=baseline` and return their stable IDs.
- [ ] Add templates and update requirement baseline with linked RAD IDs, blocker-clear statement and pre-spec verification items.
- [ ] Run `python3 -m unittest tests.unit.test_requirements_radar tests.unit.test_ledger tests.unit.test_workflow_ops tests.unit.test_templates -v`; expect PASS.
- [ ] Commit `feat: add adaptive requirements radar`.

### Task 4: 实现知识查询、复盘和正式归档

**Files:**
- Modify: `skills/grill-harness/scripts/common.py`
- Create: `skills/grill-harness/scripts/knowledge.py`
- Modify: `skills/grill-harness/scripts/grh.py`, `skills/grill-harness/scripts/state.py`
- Create templates: `知识条目.yaml`, `学习草稿.md`, `知识变更预览.md`
- Modify: `skills/grill-harness/assets/templates/项目经验.md`
- Test: `tests/unit/test_knowledge.py`
- Modify: `tests/unit/test_storage.py`, `tests/unit/test_grh_cli.py`, `tests/unit/test_templates.py`

**Interfaces:**
- Produces `知识库/项目知识/<project-id>/knowledge.yaml` and `知识库/通用知识/knowledge.yaml`。
- Produces `validate_knowledge_record()`, `query_knowledge()`, `write_learning_draft()`, `preview_promotion()`, `promote_project_knowledge()`, `promote_general_knowledge()`。
- Produces protected CLI commands `knowledge-query`, `knowledge-draft`, `knowledge-promote`。

- [ ] Write RED tests that query changes no file hash or phase, drafts remain tentative, unaccepted workflows cannot formally archive, projects are isolated, conflicts use `replaced_by`, invalidated knowledge cannot guide planning, and general promotion needs separate user approval.
- [ ] Run `python3 -m unittest tests.unit.test_knowledge tests.unit.test_storage -v`; expect failures because knowledge storage/module is absent.
- [ ] Add `knowledge: 知识库` to storage and initialize `项目知识`/`通用知识` only for mutating operations; query must not create directories.
- [ ] Validate KNW records with ID, conclusion, type, applicability/non-applicability, evidence, trust status, source workflow, timestamp, invalidation condition and replacement link.
- [ ] Implement query as read-only; draft only under current workflow `过程产物/学习草稿/`; promotion requires independent assurance completed, current acceptance artifact/evidence and user approval. General promotion requires a second approval.
- [ ] Allow the route-failure exception only as a project-level failure fact with evidence and confirmed failure class; it cannot complete archive or become general knowledge.
- [ ] Run `python3 -m unittest tests.unit.test_knowledge tests.unit.test_storage tests.unit.test_grh_cli tests.unit.test_templates -v`; expect PASS and unchanged hashes for query.
- [ ] Commit `feat: add evidence-backed knowledge lifecycle`.

### Task 5: 实现失败分类、修复轮次和 Review 收敛

**Files:**
- Create: `skills/grill-harness/scripts/failure_control.py`
- Modify: `skills/grill-harness/scripts/workflow_ops.py`, `skills/grill-harness/scripts/grh.py`
- Modify: `skills/grill-harness/assets/templates/修复任务.md`
- Test: `tests/unit/test_failure_control.py`
- Modify: `tests/unit/test_workflow_ops.py`

**Interfaces:**
- Produces `FAILURE_CLASSES`, `issue_fingerprint()`, `record_attempt()`, `next_action()`, `validate_threshold_override()`。
- Default actions: attempt 1 `minimal_fix`, attempt 2 `root_cause_recheck`, attempt 3 `recover_required`。

- [ ] Write RED tests for four failure classes, stable fingerprints, baseline separation, three-attempt escalation, threshold approval, ordinary bugs not changing routes, route failures not auto-selecting alternatives, and non-blocking review comments not preventing completion.
- [ ] Run `python3 -m unittest tests.unit.test_failure_control -v`; expect import failure.
- [ ] Implement fingerprints from issue ID, failed acceptance/command and Git baseline, not free-text wording.
- [ ] Require user-approved DEC/CHG and reason for threshold override.
- [ ] Reject a normal repair task after the third same implementation failure and recommend `grh-recover`; route/evidence/integrity failures respectively require human route selection, more evidence, or reconcile.
- [ ] Update repair template with failure class, fingerprint, attempt count/history, evidence and stop condition.
- [ ] Run `python3 -m unittest tests.unit.test_failure_control tests.unit.test_workflow_ops tests.unit.test_task_graph -v`; expect PASS.
- [ ] Commit `feat: converge review and repair failures`.

### Task 6: 更新共享协议、README 和运行时场景

**Files:**
- Modify: all `skills/grill-harness/references/*.md` relevant to workflow behavior
- Modify: `README.md`
- Modify/Create: `tests/scenarios/router/*`, `tests/scenarios/codex/*`, `tests/scenarios/claude-code/*`
- Modify: `tests/unit/test_templates.py`, `tests/unit/test_router_scenarios.py`

**Interfaces:**
- Documents the behavior already enforced by Tasks 1–5 and adds reproducible scenario evidence。

- [ ] Add RED documentation tests for eight entries, adaptive radar, analogue comparison, three knowledge modes, four failure classes, third-attempt recovery, and optional-review convergence.
- [ ] Run `python3 -m unittest tests.unit.test_templates tests.unit.test_router_scenarios -v`; expect failures against old single-entry references.
- [ ] Update stage protocol: radar before baseline, user controls investigation agents, plan stops at spec approval, run/check isolation, learn modes, and no automatic rerouting.
- [ ] Update state and artifact references: three separate gates in lightweight mode, radar files, learning drafts, project/general knowledge and formal archive prerequisites.
- [ ] Update README with entry map, actually verified install command, missing-core recovery, knowledge paths and read-only upstream workflow.
- [ ] Add scenarios for requirement-only scope, non-recommended route, review-only, unaccepted archive rejection, third repeated failure, route-failure reselection, knowledge reuse and no upstream update action.
- [ ] Run `python3 -m unittest tests.unit.test_templates tests.unit.test_router_scenarios tests.unit.test_codex_scenarios tests.unit.test_claude_code_scenarios -v`; expect PASS or explicit real-model unverified evidence.
- [ ] Commit `docs: document multi-entry grill harness workflow`.

### Task 7: 完整验证、独立审查与新版验收提示词

**Files:**
- Review: all repository files
- Create: `docs/acceptance-prompt-v2.md`
- Modify only confirmed defects found during review

**Interfaces:**
- Produces fresh verification evidence, independent code/Skill review, and a self-contained prompt for a new acceptance session。

- [ ] Run full unit tests: `python3 -m unittest discover -s tests -p 'test_*.py'`.
- [ ] Run compilation: `python3 -m py_compile skills/grill-harness/scripts/*.py`.
- [ ] Run integration: `tests/integration/test_skills_install.sh` and `tests/integration/test_runtime_data.sh`.
- [ ] Run `git diff --check`, shell syntax, secret scan, personal-path scan, runtime-boundary scan and full diff review.
- [ ] Use an independent code reviewer against `docs/design.md` and this plan; fix only evidenced Critical/Important findings with RED tests.
- [ ] Use an independent Skill reviewer to test explicit entry priority, no auto-chain, radar escalation, analogue comparison, knowledge promotion boundaries, review convergence and human route control.
- [ ] Re-run affected tests and then the full verification suite after every accepted fix.
- [ ] Create `docs/acceptance-prompt-v2.md` requiring isolated/read-only-first evaluation, no side-effect update commands, static/deterministic/real-model evidence layers, eight-entry scenarios, radar, knowledge, failure rerouting, human gates and explicit PASS thresholds.
- [ ] Commit `test: complete multi-entry harness acceptance package`.
- [ ] Report actual local/remote SHA, worktree status, test counts and commands, skills.sh result, real-model limitations, reviews and acceptance prompt path. Do not merge PR, delete branches or make the repository public without separate user authorization.
