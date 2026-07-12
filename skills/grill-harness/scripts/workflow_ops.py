"""Guarded workflow mutations for records, gates, and phase transitions."""

import copy
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import common
import failure_control
import requirements_radar
import state
import task_graph
import validate


KINDS = {
    "artifact": ("artifacts", "artifacts.yaml"),
    "task": ("tasks", "tasks.yaml"),
    "evidence": ("evidence", "evidence.yaml"),
    "ledger": ("ledger", None),
}
MANIFEST_FILES = {
    "artifacts": "artifacts.yaml",
    "tasks": "tasks.yaml",
    "evidence": "evidence.yaml",
    "failure_attempts": "failures.yaml",
}
TRANSACTION_FILE = ".workflow-transaction.yaml"


def _state_path(value):
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        nested = path / "系统" / "state.yaml"
        path = nested if nested.is_file() else path / "state.yaml"
    try:
        path.relative_to(common.resolve_storage_root())
    except ValueError:
        raise ValueError("workflow mutation is only allowed under ~/.grill-harness")
    return path


def _mapping(path):
    payload = common.read_yaml(path)
    if not isinstance(payload, dict):
        raise ValueError("machine file must be a mapping: {}".format(path))
    return payload


def _load(state_path):
    _recover_interrupted_write(state_path)
    workflow = _mapping(state_path)
    manifests = {}
    for field, filename in MANIFEST_FILES.items():
        path = state_path.parent / filename
        manifest = _mapping(path)
        if manifest.get(field) != workflow.get(field):
            raise ValueError("{} manifest contradicts state".format(field))
        manifests[field] = (path, manifest)
    failure_report = failure_control.validate_failure_chain(
        workflow.get("failure_attempts", ()),
        manifests["failure_attempts"][1],
        ledger=workflow.get("ledger", ()),
    )
    if not failure_report["valid"]:
        raise ValueError(
            "failure chain integrity conflict: {}".format(
                failure_report["conflicts"][0]["conflict"]
            )
        )
    return workflow, manifests


def _recover_interrupted_write(state_path):
    journal_path = state_path.parent / TRANSACTION_FILE
    journal = common.read_yaml(journal_path)
    if journal is None:
        return False
    if not isinstance(journal, dict) or not isinstance(journal.get("targets"), dict):
        raise ValueError("workflow transaction journal is corrupt")
    for key, target_text in journal["targets"].items():
        target = Path(target_text)
        backup_text = journal.get("backups", {}).get(key)
        if backup_text is None:
            target.unlink(missing_ok=True)
            continue
        backup = Path(backup_text)
        if not backup.is_file():
            raise ValueError("workflow transaction backup is missing: {}".format(backup))
        shutil.copy2(str(backup), str(target))
    journal_path.unlink(missing_ok=True)
    return True


def _within_storage(path):
    if not isinstance(path, str) or not os.path.isabs(path):
        return False
    try:
        Path(path).resolve().relative_to(common.resolve_storage_root())
    except ValueError:
        return False
    return True


def _within_workflow(path, workflow_root):
    if not isinstance(path, str) or not os.path.isabs(path):
        return False
    try:
        Path(path).resolve().relative_to(Path(workflow_root).resolve())
    except ValueError:
        return False
    return True


def _validate_task_contract(record, workflow_root):
    sequence_fields = (
        "depends_on",
        "blockers",
        "trace_ids",
        "acceptance_ids",
        "allowed_paths",
        "forbidden_paths",
        "write_paths",
        "shared_contracts",
        "migrations",
        "generated_files",
    )
    for field in sequence_fields:
        value = record.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError("task {} must be a string list".format(field))
    for field in ("trace_ids", "acceptance_ids", "allowed_paths", "write_paths"):
        if not record[field]:
            raise ValueError("task {} must not be empty".format(field))
    for field in (
        "status",
        "currentness",
        "parallel_group",
        "git_baseline",
        "worktree",
        "branch",
        "task_package_path",
        "startup_prompt_path",
        "output_path",
    ):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError("task {} must be a non-empty string".format(field))
    for field in ("task_package_path", "startup_prompt_path", "output_path"):
        if not _within_workflow(record[field], workflow_root):
            raise ValueError("{} must be inside the current workflow".format(field))
    if not Path(record["task_package_path"]).is_file():
        raise ValueError("task package file does not exist")
    if not Path(record["startup_prompt_path"]).is_file():
        raise ValueError("task startup prompt file does not exist")
    if record.get("review_required") is not True:
        raise ValueError("new tasks require review_required: true")
    review = record.get("review")
    _validate_review_payload(review, allow_pending=True)
    if review.get("status") != "pending" or "baseline" in review:
        raise ValueError(
            "new task review must be pending without a baseline; use task-review later"
        )
    if record.get("review_history") != []:
        raise ValueError("new task review_history must start empty")


def _validate_review_payload(review, *, allow_pending):
    if not isinstance(review, dict):
        raise ValueError("task review must be a mapping")
    allowed_statuses = {"recorded"}
    if allow_pending:
        allowed_statuses.add("pending")
    if review.get("status") not in allowed_statuses:
        raise ValueError("task review status is invalid")
    for field in (
        "goals_satisfied",
        "test_evidence_satisfied",
        "unresolved_route_issue",
    ):
        if not isinstance(review.get(field), bool):
            raise ValueError("task review {} must be boolean".format(field))
    comments = review.get("comments")
    if not isinstance(comments, list):
        raise ValueError("task review comments must be a list")
    comment_ids = [
        item.get("id") for item in comments if isinstance(item, dict)
    ]
    if len(comment_ids) != len(comments) or len(set(comment_ids)) != len(comment_ids):
        raise ValueError("task review comments require unique stable IDs")
    failure_control.review_convergence(
        comments,
        goals_satisfied=review["goals_satisfied"],
        test_evidence_satisfied=review["test_evidence_satisfied"],
        unresolved_route_issue=review["unresolved_route_issue"],
    )


def _review_classification(comment):
    value = comment.get(
        "classification", comment.get("disposition", comment.get("severity"))
    )
    aliases = {
        "blocking": "blocking",
        "must_fix": "must_fix",
        "optional": "optional",
        "optional_optimization": "optional",
        "non_blocking": "optional",
        "invalid": "invalid",
        "not_applicable": "invalid",
        "rejected": "invalid",
    }
    if value not in aliases:
        raise ValueError("unknown review classification: {}".format(value))
    return aliases[value]


def _validate_review_append(previous, current):
    if previous is None:
        previous_comments = {}
    else:
        previous_comments = {item["id"]: item for item in previous["comments"]}
    current_comments = {item["id"]: item for item in current["comments"]}
    protected = {
        comment_id
        for comment_id, comment in previous_comments.items()
        if _review_classification(comment) in {"blocking", "must_fix"}
    }
    missing = sorted(protected.difference(current_comments))
    if missing:
        raise ValueError(
            "review history cannot delete blocking or must-fix comments: {}".format(
                ", ".join(missing)
            )
        )
    rank = {"invalid": 0, "optional": 1, "must_fix": 2, "blocking": 3}
    terminal_statuses = {"resolved", "fixed", "rejected", "closed", "invalid"}
    for comment_id, comment in current_comments.items():
        classification = _review_classification(comment)
        status = comment.get("status", "open")
        if status != "open" and status not in terminal_statuses:
            raise ValueError("unknown review status for {}".format(comment_id))
        evidence = comment.get("evidence", [])
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) or not item.strip() for item in evidence
        ):
            raise ValueError("review evidence must be a string list")
        old = previous_comments.get(comment_id)
        if old is None:
            if status in terminal_statuses and not evidence:
                raise ValueError("closed review comments require evidence")
            continue
        old_classification = _review_classification(old)
        if rank[classification] < rank[old_classification]:
            raise ValueError("review classification cannot be downgraded")
        old_status = old.get("status", "open")
        old_evidence = old.get("evidence", [])
        if old_status in terminal_statuses and status != old_status:
            raise ValueError("closed review comments cannot change status")
        if old_status == "open" and status in terminal_statuses and not evidence:
            raise ValueError("closing a review comment requires evidence")
        if not set(old_evidence).issubset(evidence):
            raise ValueError("review history cannot delete existing evidence")


def _review_record_hash(review):
    payload = {key: value for key, value in review.items() if key != "review_hash"}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _seal_review_record(review, predecessor_hash, sequence):
    sealed = dict(
        copy.deepcopy(review),
        predecessor_hash=predecessor_hash,
        sequence=sequence,
    )
    sealed["review_hash"] = _review_record_hash(sealed)
    return sealed


def _validate_review_history(history):
    if not isinstance(history, list) or any(
        not isinstance(item, dict) for item in history
    ):
        raise ValueError("task review_history must be a list of mappings")
    previous_hash = None
    for index, item in enumerate(history):
        _validate_review_payload(item, allow_pending=False)
        if item.get("sequence") != index + 1:
            raise ValueError("task review_history sequence is not contiguous")
        if item.get("predecessor_hash") != previous_hash:
            raise ValueError("task review_history predecessor hash is broken")
        if item.get("review_hash") != _review_record_hash(item):
            raise ValueError("task review_history record hash is invalid")
        if index:
            _validate_review_append(history[index - 1], item)
        previous_hash = item["review_hash"]


def _validate_repair_task_policy(record, workflow):
    is_repair = (
        record.get("task_type") == "repair"
        or record.get("kind") == "repair"
        or record.get("failure_fingerprint") is not None
    )
    if not is_repair:
        return
    failure_class = record.get("failure_class")
    fingerprint = record.get(
        "failure_fingerprint", record.get("fingerprint")
    )
    if failure_class not in failure_control.FAILURE_CLASSES:
        raise ValueError("repair task requires a confirmed failure class")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ValueError("repair task requires a stable failure fingerprint")
    history = workflow.get("failure_attempts", [])
    if not isinstance(history, list):
        raise ValueError("failure_attempts must be a list")
    matching = [
        item
        for item in history
        if isinstance(item, dict) and item.get("fingerprint") == fingerprint
    ]
    if not matching:
        raise ValueError("repair task fingerprint has no recorded failure attempt")
    if any(
        not isinstance(item.get("attempt_count"), int)
        or isinstance(item.get("attempt_count"), bool)
        or item["attempt_count"] < 1
        for item in matching
    ):
        raise ValueError("recorded failure attempt_count is invalid")
    if [item["attempt_count"] for item in matching] != list(
        range(1, len(matching) + 1)
    ):
        raise ValueError(
            "recorded failure attempts must be contiguous in persistence order"
        )
    latest = matching[-1]
    if any(item.get("failure_class") != failure_class for item in matching):
        raise ValueError("repair task failure class contradicts recorded attempts")
    declared_attempt = record.get("attempt_count")
    if (
        not isinstance(declared_attempt, int)
        or isinstance(declared_attempt, bool)
        or declared_attempt < 1
        or declared_attempt != latest.get("attempt_count")
    ):
        raise ValueError("repair task attempt_count must match recorded failure history")
    if failure_control.issue_fingerprint(latest) != fingerprint:
        raise ValueError("recorded failure fingerprint contradicts its structured facts")
    threshold = latest.get("threshold")
    if threshold == failure_control.DEFAULT_ATTEMPT_THRESHOLD:
        pass
    elif isinstance(threshold, int) and not isinstance(threshold, bool):
        override = latest.get("threshold_override")
        if not isinstance(override, dict):
            raise ValueError("recorded failure threshold lacks a user-approved override")
        override_report = failure_control.validate_threshold_override(
            dict(override, threshold=threshold),
            workflow.get("ledger", ()),
            fingerprint=fingerprint,
            issue_id=latest.get("issue_id"),
        )
        if not override_report["valid"]:
            raise ValueError(override_report["conflicts"][0]["conflict"])
    else:
        raise ValueError("recorded failure threshold is invalid")
    policy = failure_control.next_action(
        failure_class,
        attempt_count=declared_attempt,
        threshold=threshold,
    )
    repair_mode = record.get("repair_mode")
    if repair_mode not in failure_control.REPAIR_MODES:
        raise ValueError("repair_mode must be one of the declared repair modes")
    ordinary = repair_mode == "ordinary"
    if ordinary and not policy["ordinary_repair_allowed"]:
        action = policy["action"]
        if action == "recover_required":
            raise ValueError(
                "third same implementation failure blocks ordinary repair; use grh-recover"
            )
        if action == "human_route_selection":
            raise ValueError(
                "route failure requires user route selection in grh-recover; no alternative is auto-selected"
            )
        if action == "more_evidence_required":
            raise ValueError("evidence failure requires more evidence before repair")
        raise ValueError("workflow integrity failure requires reconcile before repair")
    if ordinary:
        return
    required_action = {
        "recovery": "recover_required",
        "route_selection": "human_route_selection",
        "reconcile": "reconcile_required",
    }[repair_mode]
    if policy["action"] != required_action:
        raise ValueError(
            "repair_mode {} does not match the current failure action {}".format(
                repair_mode, policy["action"]
            )
        )
    approval_id = record.get(
        "repair_approval_id",
        record.get(
            "{}_approval_id".format(repair_mode),
            record.get("route_approval_id") if repair_mode == "route_selection" else None,
        ),
    )
    approval = next(
        (
            item
            for item in workflow.get("ledger", ())
            if isinstance(item, dict)
            and item.get("id") == approval_id
            and item.get("version") == record.get("repair_approval_version")
        ),
        None,
    )
    required_gate = {
        "recovery": "failure_recovery",
        "route_selection": "route_selection",
        "reconcile": "workflow_reconcile",
    }[repair_mode]
    if not (
        isinstance(approval, dict)
        and approval.get("type") in {"DEC", "CHG"}
        and approval.get("status") == "approved"
        and approval.get("approved_by") == "user"
        and approval.get("gate") == required_gate
        and approval.get("repair_mode") == repair_mode
        and approval.get("failure_fingerprint") == fingerprint
        and approval.get("issue_id") == latest.get("issue_id")
        and failure_control.approval_record_hash(approval)
        == record.get("repair_approval_hash")
        and isinstance(approval.get("reason"), str)
        and approval["reason"].strip()
    ):
        raise ValueError(
            "non-ordinary repair requires a durable user approval bound to its mode and failure"
        )


def _write(state_path, workflow, manifests, extra_payloads=None):
    system = state_path.parent
    ledger_path = state_path.parent.parent / "核心文档" / "决策账本.yaml"
    targets = {"state": state_path}
    payloads = {"state": workflow}
    for field, (path, manifest) in manifests.items():
        if field == "failure_attempts":
            updated = failure_control.failure_chain_manifest(
                workflow[field],
                integrity_origin=manifest.get("integrity_origin", "native"),
            )
        else:
            updated = dict(manifest)
            updated[field] = workflow[field]
        targets[field] = path
        payloads[field] = updated
    if "ledger" in workflow:
        targets["ledger"] = ledger_path
        payloads["ledger"] = {"records": workflow["ledger"]}
    for key, item in (extra_payloads or {}).items():
        if key in targets or not isinstance(item, tuple) or len(item) != 2:
            raise ValueError("invalid extra workflow transaction target: {}".format(key))
        target, payload = item
        target = Path(target).expanduser().resolve()
        try:
            target.relative_to(common.resolve_storage_root())
        except ValueError:
            raise ValueError("extra workflow transaction target must stay under storage")
        targets[key] = target
        payloads[key] = payload
    backup_directory = system / "事务备份" / uuid.uuid4().hex
    backup_directory.mkdir(parents=True, exist_ok=False)
    backups = {}
    for key, target in targets.items():
        if target.is_file():
            backup = backup_directory / "{}.bak".format(key)
            shutil.copy2(str(target), str(backup))
            backups[key] = str(backup)
        else:
            backups[key] = None
    temporary = Path(tempfile.mkdtemp(prefix=".workflow-write-", dir=str(system)))
    journal_path = system / TRANSACTION_FILE
    try:
        temporary_paths = {}
        for key, payload in payloads.items():
            path = temporary / "{}.yaml".format(key)
            common.atomic_write_yaml(path, payload)
            temporary_paths[key] = path
        common.atomic_write_yaml(
            journal_path,
            {
                "operation": "workflow-write",
                "targets": {key: str(path) for key, path in targets.items()},
                "backups": backups,
            },
        )
        try:
            for key, target in targets.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(temporary_paths[key]), str(target))
            journal_path.unlink(missing_ok=True)
        except OSError:
            _recover_interrupted_write(state_path)
            raise
    finally:
        shutil.rmtree(str(temporary), ignore_errors=True)


def register_record(
    workflow_value,
    kind,
    record_value,
    current_baseline=None,
    project_root=None,
):
    if kind not in KINDS:
        raise ValueError("unknown record kind: {}".format(kind))
    state_path = _state_path(workflow_value)
    workflow_root = state_path.parent.parent
    record_path = Path(record_value).expanduser().resolve()
    record = _mapping(record_path)
    field, _ = KINDS[kind]
    lock = state_path.parent / ".workflow.lock"
    with common.exclusive_directory_lock(lock):
        workflow, manifests = _load(state_path)
        records = workflow.get(field)
        if not isinstance(records, list):
            raise ValueError("{} must be a list".format(field))
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValueError("{} record requires a stable id".format(kind))
        updated_records = list(records) + [record]
        if kind == "ledger":
            state.validate_ledger(updated_records)
        elif any(
            isinstance(item, dict) and item.get("id") == record_id
            for item in records
        ):
            raise ValueError("record id already exists: {}".format(record_id))
        if kind == "artifact":
            artifact_conflicts = validate._artifact_contract_conflicts(record)
            if artifact_conflicts:
                raise ValueError(artifact_conflicts[0]["conflict"])
            if not _within_workflow(record.get("path"), workflow_root):
                raise ValueError("artifact path must be inside the current workflow")
        elif kind == "task":
            if record.get("status") != "pending" or record.get("currentness") != "current":
                raise ValueError(
                    "new task must start pending and current; use task-transition later"
                )
            _validate_task_contract(record, workflow_root)
            _validate_repair_task_policy(record, workflow)
            graph = task_graph.validate_dag(updated_records)
            if not graph["valid"]:
                raise ValueError(graph["conflicts"][0]["conflict"])
            for path_field in ("task_package_path", "startup_prompt_path", "output_path"):
                if path_field in record and not _within_workflow(
                    record.get(path_field), workflow_root
                ):
                    raise ValueError(
                        "{} must be inside ~/.grill-harness".format(path_field)
                    )
        elif kind == "evidence":
            if not isinstance(current_baseline, str) or not current_baseline:
                raise ValueError("evidence registration requires the current project baseline")
            evidence_report = validate.validate_evidence(
                record,
                current_baseline=current_baseline,
                current_time=datetime.now(timezone.utc).isoformat(),
                require_output_exists=True,
            )
            if not evidence_report["valid"]:
                raise ValueError(evidence_report["conflicts"][0]["conflict"])
            if not _within_workflow(record.get("output_path"), workflow_root):
                raise ValueError("evidence output must be inside the current workflow")
            if project_root is None:
                raise ValueError("evidence registration requires the owning project")
            try:
                Path(record.get("working_directory")).resolve().relative_to(
                    Path(project_root).expanduser().resolve()
                )
            except (TypeError, ValueError):
                raise ValueError(
                    "evidence working_directory must be inside the owning project"
                )
        updated = dict(workflow)
        updated[field] = updated_records
        if kind == "evidence":
            updated["git_baseline"] = current_baseline
        _write(state_path, updated, manifests)
    return {"kind": kind, "id": record_id, "workflow_path": str(state_path)}


def approve_gate(workflow_value, gate, approval_id, artifact_versions):
    if gate not in state.HUMAN_GATES:
        raise ValueError("unknown human gate: {}".format(gate))
    state_path = _state_path(workflow_value)
    lock = state_path.parent / ".workflow.lock"
    with common.exclusive_directory_lock(lock):
        workflow, manifests = _load(state_path)
        if gate == "requirements_baseline":
            blockers = requirements_radar.unresolved_baseline_blockers(
                workflow.get("ledger", ())
            )
            if blockers:
                raise ValueError(
                    "requirements baseline is blocked by open radar records: {}".format(
                        ", ".join(blockers)
                    )
                )
        updated = dict(workflow)
        gates = dict(workflow.get("gates", {}))
        gates[gate] = {
            "status": "approved",
            "approval_id": approval_id,
            "artifact_versions": dict(artifact_versions),
        }
        updated["gates"] = gates
        report = validate.reconcile_workflow(updated)
        gate_conflicts = [
            item
            for item in report["conflicts"]
            if item["code"] == "INVALID_GATE_BINDING"
        ]
        if gate_conflicts:
            raise ValueError(gate_conflicts[0]["conflict"])
        _write(state_path, updated, manifests)
    return {"gate": gate, "approval_id": approval_id, "workflow_path": str(state_path)}


def transition_phase(
    workflow_value,
    phase_id,
    target,
    artifacts=None,
    evidence=None,
    skip_reason=None,
    skip_approval_id=None,
):
    state_path = _state_path(workflow_value)
    lock = state_path.parent / ".workflow.lock"
    with common.exclusive_directory_lock(lock):
        workflow, manifests = _load(state_path)
        phases = workflow.get("phases")
        if not isinstance(phases, list):
            raise ValueError("phases must be a list")
        updated_phases = []
        found = False
        for phase in phases:
            if not isinstance(phase, dict) or phase.get("id") != phase_id:
                updated_phases.append(phase)
                continue
            found = True
            candidate = dict(phase)
            if artifacts is not None:
                candidate["artifacts"] = list(artifacts)
            if evidence is not None:
                candidate["evidence"] = list(evidence)
            if target == "skipped":
                if phase_id not in state.OPTIONAL_PHASES:
                    raise ValueError(
                        "phase is required and cannot be changed to optional"
                    )
                candidate["optional"] = True
                candidate["skip_reason"] = skip_reason
                candidate["skip_approval_id"] = skip_approval_id
            candidate = state.transition_state(
                candidate, target, gates=workflow.get("gates", {})
            )
            updated_phases.append(candidate)
        if not found:
            raise ValueError("unknown phase record: {}".format(phase_id))
        phase_ids = {
            item.get("id") for item in phases if isinstance(item, dict)
        }
        if phase_ids.issuperset(state.WORKFLOW_PHASES):
            target_index = state.WORKFLOW_PHASES.index(phase_id)
            incomplete = [
                item.get("id")
                for item in phases
                if isinstance(item, dict)
                and item.get("id") in state.WORKFLOW_PHASES[:target_index]
                and item.get("status")
                not in ("completed", "skipped")
            ]
            if incomplete:
                raise ValueError(
                    "previous phases must complete before {}: {}".format(
                        phase_id, ", ".join(incomplete)
                    )
                )
        updated = dict(workflow)
        updated["phases"] = updated_phases
        report = validate.reconcile_workflow(
            updated,
            current_baseline=workflow.get("git_baseline"),
            current_time=datetime.now(timezone.utc).isoformat(),
        )
        if not report["valid"]:
            raise ValueError(report["conflicts"][0]["conflict"])
        _write(state_path, updated, manifests)
    return {"phase": phase_id, "status": target, "workflow_path": str(state_path)}


def _approved_preview_decision(workflow, approval_id, gate, preview_id):
    latest = None
    for record in workflow.get("ledger", ()):
        if isinstance(record, dict) and record.get("id") == approval_id:
            latest = record
    return (
        isinstance(latest, dict)
        and latest.get("status") == "approved"
        and latest.get("approved_by") == "user"
        and latest.get("gate") == gate
        and latest.get("preview_id") == preview_id
    )


def commit_knowledge_update(
    workflow_value,
    project_id,
    scope,
    knowledge_payload,
    *,
    preview_id,
    approval_requirements,
    artifact_ids=(),
    complete_archive=False,
    route_failure=False,
    evidence_ids=(),
    expected_store_hash=None,
    expected_source_hash=None,
    project_path=None,
):
    """Atomically commit a knowledge store with its guarded workflow facts."""

    state_path = _state_path(workflow_value)
    if not isinstance(project_id, str) or not project_id or any(
        separator in project_id for separator in ("/", "\\")
    ):
        raise ValueError("project_id must be a safe stable identifier")
    if scope not in {"project", "general"}:
        raise ValueError("knowledge scope must be project or general")
    knowledge_root = (
        common.resolve_storage_root() / common.STORAGE_DIRECTORIES["knowledge"]
    )
    destination = (
        knowledge_root / "项目知识" / project_id / "knowledge.yaml"
        if scope == "project"
        else knowledge_root / "通用知识" / "knowledge.yaml"
    ).resolve()
    if not isinstance(knowledge_payload, dict):
        raise ValueError("knowledge payload must be a mapping")
    requirements = list(approval_requirements)
    if not requirements:
        raise ValueError("knowledge commit requires a persisted user approval")
    knowledge_lock = destination.parent / ".knowledge.lock"
    workflow_lock = state_path.parent / ".workflow.lock"
    source = (
        (knowledge_root / "项目知识" / project_id / "knowledge.yaml").resolve()
        if scope == "general"
        else None
    )
    lock_paths = {knowledge_lock, workflow_lock}
    if source is not None:
        lock_paths.add(source.parent / ".knowledge.lock")
    with ExitStack() as stack:
        for lock_path in sorted(lock_paths, key=lambda item: str(item)):
            stack.enter_context(common.exclusive_directory_lock(lock_path))
        current_hash = hashlib.sha256(
            destination.read_bytes() if destination.is_file() else b"<missing>"
        ).hexdigest()
        if expected_store_hash is not None and current_hash != expected_store_hash:
            raise ValueError("knowledge store changed after preview; create a new preview")
        if source is not None:
            source_hash = hashlib.sha256(
                source.read_bytes() if source.is_file() else b"<missing>"
            ).hexdigest()
            if source_hash != expected_source_hash:
                raise ValueError("project knowledge source changed after preview")
        workflow, manifests = _load(state_path)
        state.validate_ledger(workflow.get("ledger", ()))
        for requirement in requirements:
            if len(requirement) == 2:
                approval_id, gate = requirement
                bound_preview_id = preview_id
            elif len(requirement) == 3:
                approval_id, gate, bound_preview_id = requirement
            else:
                raise ValueError("invalid knowledge approval requirement")
            if not _approved_preview_decision(
                workflow, approval_id, gate, bound_preview_id
            ):
                raise ValueError(
                    "knowledge preview requires a user-approved {} decision bound to {}".format(
                        gate, bound_preview_id
                    )
                )
        updated = copy.deepcopy(workflow)
        if route_failure:
            evidence_index = {
                item.get("id"): item
                for item in workflow.get("evidence", ())
                if isinstance(item, dict)
            }
            if not evidence_ids:
                raise ValueError("route failure requires objective workflow evidence")
            for evidence_id in evidence_ids:
                evidence = evidence_index.get(evidence_id)
                if not (
                    isinstance(evidence, dict)
                    and evidence.get("status") in {"valid", "completed"}
                    and (
                        evidence.get("current") is True
                        or evidence.get("currentness") == "current"
                    )
                    and evidence.get("failure_class") == "route_failure"
                    and evidence.get("workflow_id") == workflow.get("workflow_id")
                ):
                    raise ValueError(
                        "route failure evidence must be current, owned, and classification-specific: {}".format(
                            evidence_id
                        )
                    )
        elif complete_archive:
            if project_path is None:
                raise ValueError("knowledge archive requires the current project path")
            project_root = Path(project_path).expanduser().resolve()
            if not project_root.is_dir():
                raise ValueError("knowledge archive current project path does not exist")
            project_identity = state.identify_project(project_root)
            current_baseline = state.current_project_baseline(
                project_root, project_identity
            )
            archive_approval = requirements[0][0]
            updated["archive_confirmation"] = {
                "status": "approved",
                "approval_id": archive_approval,
                "preview_id": preview_id,
            }
            missing = state.knowledge_archive_prerequisites(
                updated, current_baseline=current_baseline
            )
            if missing:
                raise ValueError(
                    "knowledge archive missing current prerequisites: {}".format(
                        ", ".join(missing)
                    )
                )
            promoted_ids = list(artifact_ids)
            if not promoted_ids:
                raise ValueError("knowledge archive requires at least one promoted record")
            acceptance_ids = [
                item["id"]
                for item in updated.get("evidence", ())
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item.get("kind") == "final_acceptance"
                and item.get("result") == "accepted"
                and (item.get("current") is True or item.get("currentness") == "current")
                and item.get("baseline") == current_baseline
            ]
            artifacts = copy.deepcopy(updated.get("artifacts", []))
            artifact_index = {
                item.get("id") for item in artifacts if isinstance(item, dict)
            }
            for record_id in promoted_ids:
                if record_id not in artifact_index:
                    artifacts.append({
                        "id": record_id,
                        "kind": "knowledge-record",
                        "version": 1,
                        "status": "completed",
                        "currentness": "current",
                        "path": str(destination),
                    })
            phases = copy.deepcopy(updated.get("phases", []))
            phase_ids = {
                item.get("id") for item in phases if isinstance(item, dict)
            }
            if phase_ids.issuperset(state.WORKFLOW_PHASES):
                archive_index = state.WORKFLOW_PHASES.index("knowledge_archive")
                incomplete = [
                    item.get("id")
                    for item in phases
                    if isinstance(item, dict)
                    and item.get("id") in state.WORKFLOW_PHASES[:archive_index]
                    and item.get("status") not in {"completed", "skipped"}
                ]
                if incomplete:
                    raise ValueError(
                        "previous phases must complete before knowledge_archive: {}".format(
                            ", ".join(incomplete)
                        )
                    )
            found = False
            for index, phase in enumerate(phases):
                if not isinstance(phase, dict) or phase.get("id") != "knowledge_archive":
                    continue
                found = True
                current_phase = phase
                if current_phase.get("status") == "pending":
                    current_phase = state.transition_state(
                        current_phase, "in_progress", gates=updated.get("gates", {})
                    )
                if current_phase.get("status") != "in_progress":
                    raise ValueError("knowledge_archive must be pending or in_progress")
                current_phase = dict(
                    current_phase,
                    artifacts=promoted_ids,
                    evidence=acceptance_ids,
                )
                phases[index] = state.transition_state(
                    current_phase, "completed", gates=updated.get("gates", {})
                )
                break
            if not found:
                raise ValueError("workflow knowledge_archive phase is missing")
            updated["artifacts"] = artifacts
            updated["phases"] = phases
        else:
            archive_phase = next(
                (
                    item for item in updated.get("phases", ())
                    if isinstance(item, dict) and item.get("id") == "knowledge_archive"
                ),
                None,
            )
            if not isinstance(archive_phase, dict) or archive_phase.get("status") != "completed":
                raise ValueError("general knowledge requires completed project knowledge archive")
            general_approval = requirements[-1][0]
            updated["general_knowledge_confirmation"] = {
                "status": "approved",
                "approval_id": general_approval,
                "preview_id": preview_id,
            }
        _write(
            state_path,
            updated,
            manifests,
            extra_payloads={"knowledge": (destination, knowledge_payload)},
        )
    return {"workflow_path": str(state_path), "knowledge_path": str(destination)}


def transition_task(
    workflow_value,
    task_id,
    target,
    evidence=None,
    current_baseline=None,
):
    state_path = _state_path(workflow_value)
    workflow_root = state_path.parent.parent
    lock = state_path.parent / ".workflow.lock"
    with common.exclusive_directory_lock(lock):
        workflow, manifests = _load(state_path)
        tasks = workflow.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("tasks must be a list")
        updated_tasks = []
        found = False
        for task in tasks:
            if not isinstance(task, dict) or task.get("id") != task_id:
                updated_tasks.append(task)
                continue
            found = True
            if not isinstance(current_baseline, str) or not current_baseline:
                raise ValueError("task transition requires the current project baseline")
            if target == "in_progress" and task.get("git_baseline") != current_baseline:
                raise ValueError(
                    "task Git baseline no longer matches the owning project"
                )
            state.validate_transition(task.get("status"), target)
            candidate = dict(task)
            candidate["status"] = target
            if target == "completed":
                evidence_ids = list(evidence or ())
                if not evidence_ids:
                    raise ValueError("completed task requires evidence IDs")
                evidence_index = {
                    item.get("id"): item
                    for item in workflow.get("evidence", ())
                    if isinstance(item, dict)
                }
                for evidence_id in evidence_ids:
                    evidence_record = evidence_index.get(evidence_id)
                    if evidence_record is None:
                        raise ValueError(
                            "completed task references missing evidence: {}".format(
                                evidence_id
                            )
                        )
                    report = validate.validate_evidence(
                        evidence_record,
                        current_baseline=current_baseline,
                        current_time=datetime.now(timezone.utc).isoformat(),
                        require_output_exists=True,
                    )
                    if not report["valid"]:
                        raise ValueError(report["conflicts"][0]["conflict"])
                    if task_id not in evidence_record.get("tasks", ()):
                        raise ValueError(
                            "task evidence does not trace the completed task"
                        )
                    if not _within_workflow(
                        evidence_record.get("output_path"), workflow_root
                    ):
                        raise ValueError(
                            "task evidence output must be inside the current workflow"
                        )
                candidate["review_convergence"] = _validate_task_review_completion(
                    candidate,
                    workflow,
                    evidence_index,
                    current_baseline=current_baseline,
                    workflow_root=workflow_root,
                )
                if not Path(candidate["output_path"]).is_file():
                    raise ValueError("completed task report does not exist")
                candidate["evidence"] = evidence_ids
                candidate["currentness"] = "current"
            updated_tasks.append(candidate)
        if not found:
            raise ValueError("unknown task: {}".format(task_id))
        updated = dict(workflow)
        updated["tasks"] = updated_tasks
        if target == "completed":
            updated["git_baseline"] = current_baseline
        graph = task_graph.validate_dag(updated_tasks)
        if not graph["valid"]:
            raise ValueError(graph["conflicts"][0]["conflict"])
        _write(state_path, updated, manifests)
    return {"task": task_id, "status": target, "workflow_path": str(state_path)}


def record_task_review(
    workflow_value,
    task_id,
    review,
    *,
    current_baseline,
):
    """Persist review facts for a review-required task under the workflow lock."""

    if not isinstance(current_baseline, str) or not current_baseline.strip():
        raise ValueError("task review requires the current project baseline")
    _validate_review_payload(review, allow_pending=False)
    state_path = _state_path(workflow_value)
    lock = state_path.parent / ".workflow.lock"
    with common.exclusive_directory_lock(lock):
        workflow, manifests = _load(state_path)
        tasks = workflow.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("tasks must be a list")
        updated_tasks = []
        found = False
        for task in tasks:
            if not isinstance(task, dict) or task.get("id") != task_id:
                updated_tasks.append(task)
                continue
            found = True
            if task.get("review_required") is False:
                raise ValueError("task is not declared review-required")
            if task.get("status") not in {"in_progress", "blocked"}:
                raise ValueError("task review can only be recorded while work is active")
            candidate = dict(task)
            history = candidate.get("review_history")
            if history is None:
                existing_review = candidate.get("review")
                history = (
                    [
                        _seal_review_record(
                            existing_review,
                            None,
                            1,
                        )
                    ]
                    if isinstance(existing_review, dict)
                    and existing_review.get("status") == "recorded"
                    else []
                )
            _validate_review_history(history)
            recorded_review = _seal_review_record(
                dict(copy.deepcopy(review), baseline=current_baseline),
                history[-1]["review_hash"] if history else None,
                len(history) + 1,
            )
            _validate_review_append(history[-1] if history else None, recorded_review)
            candidate["review_required"] = True
            candidate["review_history"] = list(history) + [recorded_review]
            candidate["review"] = copy.deepcopy(recorded_review)
            updated_tasks.append(candidate)
        if not found:
            raise ValueError("unknown task: {}".format(task_id))
        updated = dict(workflow)
        updated["tasks"] = updated_tasks
        _write(state_path, updated, manifests)
    return {"task": task_id, "review_status": "recorded", "workflow_path": str(state_path)}


def _validate_task_review_completion(
    task,
    workflow,
    evidence_index,
    *,
    current_baseline,
    workflow_root,
):
    if task.get("review_required") is not True:
        raise ValueError("task completion requires review_required: true")
    history = task.get("review_history")
    if not isinstance(history, list) or not history:
        raise ValueError("task completion requires append-only review_history")
    _validate_review_history(history)
    review = history[-1]
    if task.get("review") != review:
        raise ValueError("current task review must be derived from review_history")
    _validate_review_payload(review, allow_pending=False)
    if review.get("baseline") != current_baseline:
        raise ValueError("task review baseline is missing or no longer current")
    summary = failure_control.review_convergence(
        review["comments"],
        goals_satisfied=review["goals_satisfied"],
        test_evidence_satisfied=review["test_evidence_satisfied"],
        unresolved_route_issue=review["unresolved_route_issue"],
    )
    if not summary["completion_allowed"]:
        blockers = (
            summary["unresolved_review_ids"]
            + summary["missing_review_evidence_ids"]
        )
        raise ValueError(
            "task review has not converged: {}".format(
                ", ".join(blockers) or "review goals/evidence/route facts"
            )
        )
    for comment in review["comments"]:
        classification = comment.get(
            "classification", comment.get("disposition", comment.get("severity"))
        )
        if classification != "must_fix":
            continue
        for evidence_id in comment.get("evidence", ()):
            evidence_record = evidence_index.get(evidence_id)
            if evidence_record is None:
                raise ValueError(
                    "must-fix {} references missing evidence {}".format(
                        comment["id"], evidence_id
                    )
                )
            report = validate.validate_evidence(
                evidence_record,
                current_baseline=current_baseline,
                current_time=datetime.now(timezone.utc).isoformat(),
                require_output_exists=True,
            )
            if not report["valid"]:
                raise ValueError(report["conflicts"][0]["conflict"])
            if task["id"] not in evidence_record.get("tasks", ()):
                raise ValueError(
                    "must-fix evidence {} does not trace task {}".format(
                        evidence_id, task["id"]
                    )
                )
            if comment["id"] not in evidence_record.get("issues", ()):
                raise ValueError(
                    "must-fix {} is not traced by evidence {}".format(
                        comment["id"], evidence_id
                    )
                )
            if not _within_workflow(evidence_record.get("output_path"), workflow_root):
                raise ValueError("must-fix evidence output must be inside the current workflow")
    return summary


def record_failure_attempt(
    workflow_value,
    failure,
    *,
    current_baseline,
    threshold_override=None,
):
    """Atomically append one classified failure attempt to workflow state."""

    if not isinstance(current_baseline, str) or not current_baseline.strip():
        raise ValueError("failure recording requires the current project baseline")
    if not isinstance(failure, dict):
        raise ValueError("failure facts must be a mapping")
    state_path = _state_path(workflow_value)
    lock = state_path.parent / ".workflow.lock"
    with common.exclusive_directory_lock(lock):
        workflow, manifests = _load(state_path)
        history = workflow.get("failure_attempts", [])
        if not isinstance(history, list):
            raise ValueError("failure_attempts must be a list")
        existing_fingerprint = failure.get("fingerprint")
        new_chain = failure.get("new_chain") is True
        if new_chain and existing_fingerprint is not None:
            raise ValueError("new chain cannot also select an existing fingerprint")
        requested_key = failure_control.failure_chain_key(failure)
        candidate_fingerprints = []
        for item in history:
            if not isinstance(item, dict):
                raise ValueError("failure_attempts entries must be mappings")
            if failure_control.failure_chain_key(item) != requested_key:
                continue
            candidate = item.get("fingerprint")
            if not isinstance(candidate, str) or not candidate.strip():
                raise ValueError("existing failure chain candidate has no fingerprint")
            if candidate not in candidate_fingerprints:
                candidate_fingerprints.append(candidate)
        if not new_chain and existing_fingerprint is None:
            if len(candidate_fingerprints) == 1:
                existing_fingerprint = candidate_fingerprints[0]
                failure = dict(failure, fingerprint=existing_fingerprint)
            elif len(candidate_fingerprints) > 1:
                raise ValueError(
                    "multiple existing failure chains match; select one fingerprint or approve a new chain"
                )
        elif not new_chain and candidate_fingerprints and existing_fingerprint not in candidate_fingerprints:
            raise ValueError("provided failure fingerprint does not match the existing chain candidate")
        originating_baseline = failure.get("originating_baseline")
        if not new_chain and existing_fingerprint is not None:
            matching = [
                item
                for item in history
                if isinstance(item, dict)
                and item.get("fingerprint") == existing_fingerprint
            ]
            if not matching:
                raise ValueError("existing failure fingerprint was not found")
            originating_baselines = {
                item.get("originating_baseline", item.get("git_baseline"))
                for item in matching
            }
            if len(originating_baselines) != 1 or not all(originating_baselines):
                raise ValueError("existing failure chain has no stable originating baseline")
            originating_baseline = next(iter(originating_baselines))
        if new_chain:
            originating_baseline = current_baseline
            new_fingerprint = failure_control.issue_fingerprint(
                dict(failure, originating_baseline=originating_baseline)
            )
            if new_fingerprint in candidate_fingerprints:
                raise ValueError("new failure chain must use a different originating baseline")
            approval_id = failure.get("new_chain_approval_id")
            reason = failure.get("new_chain_reason")
            approval = next(
                (
                    item
                    for item in reversed(list(workflow.get("ledger", ())))
                    if isinstance(item, dict) and item.get("id") == approval_id
                ),
                None,
            )
            if not (
                isinstance(reason, str)
                and reason.strip()
                and isinstance(approval, dict)
                and approval.get("type") in {"DEC", "CHG"}
                and approval.get("status") == "approved"
                and approval.get("approved_by") == "user"
                and approval.get("gate") == "new_failure_chain"
                and approval.get("failure_fingerprint") == new_fingerprint
                and approval.get("issue_id") == failure.get("issue_id")
                and approval.get("failure_class") == failure.get("failure_class")
                and approval.get("originating_baseline") == originating_baseline
                and approval.get("reason") == reason.strip()
            ):
                raise ValueError(
                    "new failure chain requires a durable user DEC/CHG bound to the new chain and reason"
                )
            failure = dict(
                failure,
                fingerprint=new_fingerprint,
                new_chain_approval_version=approval.get("version"),
                new_chain_approval_hash=failure_control.approval_record_hash(approval),
            )
        if originating_baseline is None:
            originating_baseline = current_baseline
        facts = dict(
            failure,
            originating_baseline=originating_baseline,
            current_baseline=current_baseline,
        )
        report = failure_control.record_attempt(
            history,
            facts,
            threshold_override=threshold_override,
            ledger=workflow.get("ledger", ()),
        )
        sealed_record = failure_control.seal_failure_record(
            report["record"],
            history[-1].get("record_hash") if history else None,
        )
        sealed_history = list(history) + [sealed_record]
        chain_report = failure_control.validate_failure_chain(
            sealed_history,
            failure_control.failure_chain_manifest(sealed_history),
            ledger=workflow.get("ledger", ()),
        )
        if not chain_report["valid"]:
            raise ValueError(chain_report["conflicts"][0]["conflict"])
        report["record"] = sealed_record
        report["history"] = sealed_history
        updated = dict(workflow)
        updated["failure_attempts"] = sealed_history
        _write(state_path, updated, manifests)
    result = {key: value for key, value in report.items() if key != "history"}
    result["workflow_path"] = str(state_path)
    return result


def parse_artifact_versions(values):
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("artifact version must use ID=VERSION")
        artifact_id, raw_version = value.split("=", 1)
        version = int(raw_version)
        if not artifact_id or version < 1:
            raise ValueError("artifact version must use ID=positive-integer")
        result[artifact_id] = version
    if not result:
        raise ValueError("at least one artifact version is required")
    return result


__all__ = [
    "approve_gate",
    "parse_artifact_versions",
    "commit_knowledge_update",
    "record_failure_attempt",
    "record_task_review",
    "register_record",
    "transition_task",
    "transition_phase",
]
