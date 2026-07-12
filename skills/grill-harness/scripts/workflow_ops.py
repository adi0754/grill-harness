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
    for field, filename in KINDS.values():
        if filename is None:
            continue
        path = state_path.parent / filename
        manifest = _mapping(path)
        if manifest.get(field) != workflow.get(field):
            raise ValueError("{} manifest contradicts state".format(field))
        manifests[field] = (path, manifest)
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
    if latest.get("failure_class") != failure_class:
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
            dict(override, threshold=threshold), workflow.get("ledger", ())
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
    ordinary = record.get("repair_mode", "ordinary") == "ordinary"
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


def _write(state_path, workflow, manifests, extra_payloads=None):
    system = state_path.parent
    ledger_path = state_path.parent.parent / "核心文档" / "决策账本.yaml"
    targets = {"state": state_path}
    payloads = {"state": workflow}
    for field, (path, manifest) in manifests.items():
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
        facts = dict(failure, git_baseline=current_baseline)
        report = failure_control.record_attempt(
            history,
            facts,
            threshold_override=threshold_override,
            ledger=workflow.get("ledger", ()),
        )
        updated = dict(workflow)
        updated["failure_attempts"] = report["history"]
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
    "register_record",
    "transition_task",
    "transition_phase",
]
