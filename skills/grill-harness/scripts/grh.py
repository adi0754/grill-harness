#!/usr/bin/env python3
"""Read-only machine JSON entry point for Grill Harness."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import common
import entry_contract
import migration
import preflight
import state
import upstream_check
import validate
import workflow_ops


TERMINAL_PHASE_STATES = {"completed", "skipped", "superseded", "cancelled"}
UNENTERED_PHASE_STATES = {"pending", "skipped", "superseded", "cancelled"}


def _emit(payload):
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


class MachineJsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        parts = self.prog.split()
        command = parts[-1] if len(parts) > 1 else None
        _emit(
            {
                "ok": False,
                "command": command,
                "error": {
                    "type": "usage",
                    "message": (
                        "命令参数无效：{}。当前操作未执行，也不会自动修改状态；"
                        "请按 --help 修正参数后重试。"
                    ).format(message),
                },
            }
        )
        raise SystemExit(2)


def _project_payload(project):
    payload = asdict(project)
    payload["history_roots"] = list(payload["history_roots"])
    payload["relocation_candidates"] = list(payload["relocation_candidates"])
    return payload


def _workflow_file(path):
    source = Path(path).expanduser().resolve()
    if not source.is_dir():
        return source
    system_state = source / "系统" / "state.yaml"
    return system_state if system_state.is_file() else source / "state.yaml"


def _stored_project_directory(identity):
    storage_root = common.resolve_storage_root()
    projects_root = storage_root / common.STORAGE_DIRECTORIES["projects"]
    exact = projects_root / identity.directory_name
    if exact.is_dir():
        return exact
    index_path = storage_root / "项目索引.yaml"
    index = common.read_yaml(index_path, default={})
    records = index.get("projects", ()) if isinstance(index, Mapping) else ()
    relocation_keys = set(identity.relocation_candidates)
    matches = []
    if relocation_keys and isinstance(records, list):
        for record in records:
            if not isinstance(record, Mapping):
                continue
            stored_keys = set(record.get("relocation_candidates", ()))
            if relocation_keys.intersection(stored_keys):
                candidate = projects_root / str(record.get("directory_name", ""))
                if candidate.is_dir():
                    matches.append(candidate)
    unique = sorted(set(matches))
    if len(unique) > 1:
        raise ValueError(
            "multiple relocated project candidates found; user selection required: {}".format(
                ", ".join(str(path) for path in unique)
            )
        )
    return unique[0] if unique else exact


def _discover_workflow(identity):
    workflows = _stored_project_directory(identity) / "工作流"
    candidates = sorted(workflows.glob("*/系统/state.yaml")) if workflows.is_dir() else []
    if len(candidates) > 1:
        raise ValueError(
            "multiple workflows found; pass --workflow: {}".format(
                ", ".join(str(path) for path in candidates)
            )
        )
    return candidates[0] if candidates else None


def _identity_for_stored_project(identity):
    project_directory = _stored_project_directory(identity)
    if not project_directory.is_dir() or project_directory.name == identity.directory_name:
        return identity
    info = common.read_yaml(project_directory / "项目信息.yaml", default={})
    if not isinstance(info, Mapping):
        raise ValueError("stored relocated project info is invalid")
    return state.ProjectIdentity(
        project_id=info["project_id"],
        directory_name=info["directory_name"],
        normalized_path=identity.normalized_path,
        is_git=identity.is_git,
        normalized_remote=identity.normalized_remote,
        history_roots=identity.history_roots,
        relocation_candidates=identity.relocation_candidates,
    )


def _current_baseline(project_path, identity):
    result = subprocess.run(
        ["git", "-C", str(Path(project_path).expanduser().resolve()), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        head = result.stdout.strip()
        status = subprocess.run(
            [
                "git",
                "-C",
                str(Path(project_path).expanduser().resolve()),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode == 0 and status.stdout:
            project_root = Path(project_path).expanduser().resolve()
            diff = subprocess.run(
                ["git", "-C", str(project_root), "diff", "--binary", "HEAD"],
                capture_output=True,
                check=False,
            )
            untracked = subprocess.run(
                [
                    "git",
                    "-C",
                    str(project_root),
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ],
                capture_output=True,
                check=False,
            )
            digest_input = bytearray(status.stdout.encode("utf-8"))
            digest_input.extend(diff.stdout)
            for raw_path in sorted(
                item for item in untracked.stdout.split(b"\0") if item
            ):
                digest_input.extend(b"\0path:")
                digest_input.extend(raw_path)
                candidate = project_root / os.fsdecode(raw_path)
                if candidate.is_file():
                    digest_input.extend(b"\0content:")
                    digest_input.extend(candidate.read_bytes())
            digest = hashlib.sha256(bytes(digest_input)).hexdigest()[:16]
            return "{}+dirty:{}".format(head, digest)
        return head
    return identity.project_id


def _manifest_conflicts(workflow_path, workflow):
    if workflow.get("schema_version") is None:
        return []
    conflicts = []
    system_directory = workflow_path.parent
    for filename, field in (
        ("artifacts.yaml", "artifacts"),
        ("tasks.yaml", "tasks"),
        ("evidence.yaml", "evidence"),
    ):
        path = system_directory / filename
        try:
            payload = _read_mapping(path, field + " manifest")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            conflicts.append(
                {
                    "code": "MANIFEST_DIVERGENCE",
                    "conflict": "{} 无法作为权威清单读取：{}".format(path, error),
                    "recovery_action": "保留 state 与清单原文件，由用户确认正确版本后再继续。",
                    "field": field,
                }
            )
            continue
        if payload.get(field) != workflow.get(field):
            conflicts.append(
                {
                    "code": "MANIFEST_DIVERGENCE",
                    "conflict": "{} 与 state.yaml 中的 {} 不一致。".format(path, field),
                    "recovery_action": "停止受影响阶段，保留两份事实并由用户确认权威版本。",
                    "field": field,
                }
            )
    return conflicts


def _workflow_root(workflow_path):
    return workflow_path.parent.parent if workflow_path.parent.name == "系统" else None


def _phase_summary(workflow, reconciliation):
    phase_records = workflow.get("phases", ())
    if not isinstance(phase_records, list):
        phase_records = ()
    phases = {
        item.get("id"): item
        for item in phase_records
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    current = next(
        (
            phase_id
            for phase_id in state.WORKFLOW_PHASES
            if phase_id in phases
            and phases[phase_id].get("status") not in TERMINAL_PHASE_STATES
            and phases[phase_id].get("status") != "pending"
        ),
        None,
    )
    if current is None:
        current = next(
            (
                phase_id
                for phase_id in state.WORKFLOW_PHASES
                if phase_id in phases and phases[phase_id].get("status") == "pending"
            ),
            None,
        )
    if current is None:
        current = next(
            (
                phase_id
                for phase_id in reversed(state.WORKFLOW_PHASES)
                if phase_id in phases and phases[phase_id].get("status") == "completed"
            ),
            None,
        )
    if not reconciliation.get("valid"):
        return current, None
    gates = workflow.get("gates", {})
    if current is not None:
        try:
            state.validate_phase_entry(current, gates)
        except (ValueError, state.StateContractError):
            pass
        else:
            return current, current
    for phase_id in state.WORKFLOW_PHASES:
        phase = phases.get(phase_id)
        if phase and phase.get("status") in TERMINAL_PHASE_STATES:
            continue
        try:
            state.validate_phase_entry(phase_id, gates)
        except (ValueError, state.StateContractError):
            continue
        return current, phase_id
    return current, None


def _reconcile_workflow(
    workflow,
    *,
    current_baseline=None,
    current_time=None,
    manifest_conflicts=(),
    workflow_root=None,
):
    report = validate.reconcile_workflow(
        workflow,
        current_baseline=current_baseline,
        current_time=current_time,
        storage_root=str(workflow_root) if workflow_root is not None else None,
    )
    conflicts = list(report.get("conflicts", ()))
    conflicts.extend(manifest_conflicts)
    gates = workflow.get("gates", {})
    if not isinstance(gates, Mapping):
        conflicts.append(
            {
                "code": "PHASE_GATE",
                "conflict": "workflow gates must be a mapping",
                "recovery_action": "stop guarded phases and restore the persisted gate mapping",
            }
        )
        gates = {}
    phase_records = workflow.get("phases", ())
    if not isinstance(phase_records, list):
        phase_records = ()
    for phase in phase_records:
        if not isinstance(phase, dict):
            continue
        phase_id = phase.get("id")
        phase_status = phase.get("status")
        if phase_id not in state.WORKFLOW_PHASES or phase_status in UNENTERED_PHASE_STATES:
            continue
        try:
            state.validate_phase_entry(phase_id, gates)
        except (ValueError, state.StateContractError) as error:
            conflicts.append(
                {
                    "code": "PHASE_GATE",
                    "conflict": "phase {} with status {} violates its gate: {}".format(
                        phase_id,
                        phase_status,
                        error,
                    ),
                    "recovery_action": "stop the affected phase and restore or approve the required artifact-bound gate",
                    "phase_id": phase_id,
                    "status": phase_status,
                }
            )
    merged = dict(report)
    merged.update({"valid": not conflicts, "conflicts": conflicts})
    return merged


def _identify(args):
    identity = state.identify_project(Path(args.project))
    return 0, {"ok": True, "command": "identify", "project": _project_payload(identity)}


def _preflight(args):
    report = preflight.run_preflight(skill_roots=tuple(args.skill_root))
    return (0 if report["ready"] else 1), {
        "ok": report["ready"],
        "command": "preflight",
        "preflight": report,
    }


def _read_mapping(path, label):
    value = common.read_yaml(path)
    if not isinstance(value, dict):
        raise ValueError("{} must be a JSON-compatible YAML mapping: {}".format(label, path))
    return value


def _validate_existing_workflow(
    workflow_directory,
    identity,
    workflow_identifier,
    workflow_name,
    workflow_key,
    created_on,
):
    system_directory = workflow_directory / "系统"
    state_path = system_directory / "state.yaml"
    state_payload = _read_mapping(state_path, "workflow state")
    expected_identity = {
        "project_id": identity.project_id,
        "workflow_id": workflow_identifier,
        "workflow_name": workflow_name,
        "workflow_key": workflow_key,
        "created_date": created_on.isoformat(),
    }
    actual_identity = {
        field: state_payload.get(field)
        for field in expected_identity
    }
    if actual_identity != expected_identity:
        raise ValueError(
            "workflow identity conflicts with init request: {}".format(state_path)
        )
    if state_payload.get("schema_version") != 1:
        raise ValueError("workflow state schema_version must be 1: {}".format(state_path))
    if state_payload.get("workflow_version") != 1:
        raise ValueError(
            "workflow state workflow_version must be 1; run migration first: {}".format(
                state_path
            )
        )
    for field in ("phases", "artifacts", "tasks", "evidence", "ledger"):
        if not isinstance(state_payload.get(field), list):
            raise ValueError("workflow state {} must be a list: {}".format(field, state_path))
    if not isinstance(state_payload.get("gates"), dict):
        raise ValueError("workflow state gates must be a mapping: {}".format(state_path))

    for filename, field in (
        ("artifacts.yaml", "artifacts"),
        ("tasks.yaml", "tasks"),
        ("evidence.yaml", "evidence"),
    ):
        path = system_directory / filename
        payload = _read_mapping(path, field + " manifest")
        if payload.get("schema_version") != 1 or payload.get("workflow_version") != 1:
            raise ValueError(
                "{} manifest version must be schema 1 / workflow 1: {}".format(
                    field, path
                )
            )
        if not isinstance(payload.get(field), list):
            raise ValueError("{} manifest {} must be a list: {}".format(field, field, path))
        if payload[field] != state_payload[field]:
            raise ValueError(
                "{} manifest contradicts workflow state: {}".format(field, path)
            )


def _update_project_index(project_index_path, project_record):
    lock_path = project_index_path.parent / ".项目索引.lock"
    with common.exclusive_directory_lock(lock_path):
        if project_index_path.exists():
            project_index = _read_mapping(project_index_path, "project index")
            projects = project_index.get("projects")
            if not isinstance(projects, list):
                raise ValueError(
                    "project index projects must be a list: {}".format(project_index_path)
                )
        else:
            project_index = {"projects": []}
            projects = project_index["projects"]
        matching = [
            item
            for item in projects
            if isinstance(item, dict)
            and item.get("project_id") == project_record["project_id"]
        ]
        if matching and matching != [project_record]:
            existing = matching[0] if len(matching) == 1 else {}
            relocation_compatible = (
                existing.get("directory_name") == project_record["directory_name"]
                and existing.get("normalized_remote") == project_record["normalized_remote"]
                and existing.get("history_roots") == project_record["history_roots"]
            )
            if not relocation_compatible:
                raise ValueError(
                    "project index conflicts with identified project: {}".format(
                        project_index_path
                    )
                )
            updated_index = dict(project_index)
            updated_index["projects"] = [
                project_record
                if isinstance(item, dict)
                and item.get("project_id") == project_record["project_id"]
                else item
                for item in projects
            ]
            common.atomic_write_yaml(project_index_path, updated_index)
        elif not matching:
            updated_index = dict(project_index)
            updated_index["projects"] = list(projects) + [project_record]
            common.atomic_write_yaml(project_index_path, updated_index)


def _initialize_workflow(
    identity, workflow_name, workflow_key, created_on, git_baseline
):
    root_paths = common.ensure_storage_layout()
    storage_root = common.resolve_storage_root()
    project_index_path = storage_root / "项目索引.yaml"
    project_directory = root_paths["projects"] / identity.directory_name
    project_info_path = project_directory / "项目信息.yaml"
    workflow_identifier = state.workflow_id(identity.project_id, workflow_key)
    workflow_directory = (
        project_directory
        / "工作流"
        / state.workflow_directory_name(
            workflow_name,
            identity.project_id,
            workflow_key,
            created_on,
        )
    )
    directory_names = ("核心文档", "过程产物", "最终产物", "系统")
    required_directories = tuple(workflow_directory / name for name in directory_names)
    system_payloads = {
        "state.yaml": {
            "schema_version": 1,
            "workflow_version": 1,
            "git_baseline": git_baseline,
            "project_id": identity.project_id,
            "workflow_id": workflow_identifier,
            "workflow_name": workflow_name,
            "workflow_key": workflow_key,
            "created_date": created_on.isoformat(),
            "phases": [
                {"id": phase_id, "status": "pending"}
                for phase_id in state.WORKFLOW_PHASES
            ],
            "artifacts": [],
            "tasks": [],
            "evidence": [],
            "ledger": [],
            "gates": {},
        },
        "artifacts.yaml": {"schema_version": 1, "workflow_version": 1, "artifacts": []},
        "tasks.yaml": {"schema_version": 1, "workflow_version": 1, "tasks": []},
        "evidence.yaml": {"schema_version": 1, "workflow_version": 1, "evidence": []},
    }
    required_files = tuple(workflow_directory / "系统" / name for name in system_payloads)

    project_record = {
        "project_id": identity.project_id,
        "directory_name": identity.directory_name,
        "normalized_path": identity.normalized_path,
        "is_git": identity.is_git,
        "normalized_remote": identity.normalized_remote,
        "history_roots": list(identity.history_roots),
        "relocation_candidates": list(identity.relocation_candidates),
    }
    if project_info_path.exists():
        existing_project = _read_mapping(project_info_path, "project info")
        if existing_project != project_record:
            relocation_compatible = (
                existing_project.get("project_id") == project_record["project_id"]
                and existing_project.get("directory_name") == project_record["directory_name"]
                and existing_project.get("normalized_remote") == project_record["normalized_remote"]
                and existing_project.get("history_roots") == project_record["history_roots"]
            )
            if not relocation_compatible:
                raise ValueError(
                    "project info conflicts with identified project: {}".format(
                        project_info_path
                    )
                )

    if project_index_path.exists():
        project_index = _read_mapping(project_index_path, "project index")
        projects = project_index.get("projects")
        if not isinstance(projects, list):
            raise ValueError("project index projects must be a list: {}".format(project_index_path))
        matching = [item for item in projects if isinstance(item, dict) and item.get("project_id") == identity.project_id]
        if matching and matching != [project_record]:
            existing = matching[0] if len(matching) == 1 else {}
            relocation_compatible = (
                existing.get("directory_name") == project_record["directory_name"]
                and existing.get("normalized_remote") == project_record["normalized_remote"]
                and existing.get("history_roots") == project_record["history_roots"]
            )
            if not relocation_compatible:
                raise ValueError(
                    "project index conflicts with identified project: {}".format(
                        project_index_path
                    )
                )
    else:
        project_index = {"projects": []}
        projects = project_index["projects"]
        matching = []

    if workflow_directory.exists():
        missing = [str(path) for path in required_directories if not path.is_dir()]
        missing.extend(str(path) for path in required_files if not path.is_file())
        if missing:
            raise ValueError(
                "existing workflow is incomplete; refusing to overwrite user data: {}".format(
                    ", ".join(missing)
                )
            )
        _validate_existing_workflow(
            workflow_directory,
            identity,
            workflow_identifier,
            workflow_name,
            workflow_key,
            created_on,
        )
        created = False
    else:
        workflows_directory = workflow_directory.parent
        workflows_directory.mkdir(parents=True, exist_ok=True)
        temporary = workflows_directory / ".{}.{}.tmp".format(
            workflow_directory.name,
            state.new_workflow_id(),
        )
        try:
            for name in directory_names:
                (temporary / name).mkdir(parents=True, exist_ok=False)
            for filename, payload in system_payloads.items():
                common.atomic_write_yaml(temporary / "系统" / filename, payload)
            try:
                temporary.rename(workflow_directory)
            except OSError:
                if not workflow_directory.is_dir():
                    raise
                _validate_existing_workflow(
                    workflow_directory,
                    identity,
                    workflow_identifier,
                    workflow_name,
                    workflow_key,
                    created_on,
                )
                created = False
            else:
                created = True
        finally:
            if temporary.exists():
                shutil.rmtree(str(temporary))

    if (
        not project_info_path.exists()
        or _read_mapping(project_info_path, "project info") != project_record
    ):
        common.atomic_write_yaml(project_info_path, project_record)
    _update_project_index(project_index_path, project_record)
    return created, workflow_identifier, workflow_directory


def _init(args):
    try:
        created_on = date.fromisoformat(args.created_date)
    except ValueError as error:
        raise ValueError("created date must use YYYY-MM-DD: {}".format(error))
    workflow_name = args.workflow_name.strip()
    if not workflow_name:
        raise ValueError("workflow name must not be empty")
    workflow_key = (args.workflow_key or workflow_name).strip()
    if not workflow_key:
        raise ValueError("workflow key must not be empty")
    identity = _identity_for_stored_project(
        state.identify_project(Path(args.project))
    )
    git_baseline = _current_baseline(args.project, identity)
    created, workflow_identifier, workflow_path = _initialize_workflow(
        identity,
        workflow_name,
        workflow_key,
        created_on,
        git_baseline,
    )
    return 0, {
        "ok": True,
        "command": "init",
        "created": created,
        "project_id": identity.project_id,
        "workflow_id": workflow_identifier,
        "workflow_path": str(workflow_path),
    }


def _reconcile(args):
    workflow_path = _workflow_file(args.workflow)
    workflow = common.read_yaml(workflow_path)
    if not isinstance(workflow, dict):
        raise ValueError("workflow must be a JSON-compatible YAML mapping: {}".format(workflow_path))
    identity = state.identify_project(Path(args.project)) if args.project else None
    baseline = (
        _current_baseline(args.project, identity)
        if identity is not None
        else workflow.get("git_baseline")
    )
    report = _reconcile_workflow(
        workflow,
        current_baseline=baseline,
        current_time=datetime.now(timezone.utc).isoformat(),
        manifest_conflicts=_manifest_conflicts(workflow_path, workflow),
        workflow_root=_workflow_root(workflow_path),
    )
    return (0 if report["valid"] else 1), {
        "ok": report["valid"],
        "command": "reconcile",
        "workflow_path": str(workflow_path),
        "reconciliation": report,
    }


def _status(args):
    identity = state.identify_project(Path(args.project))
    workflow_path = _workflow_file(args.workflow) if args.workflow else _discover_workflow(identity)
    base = {
        "ok": True,
        "command": "status",
        "project": _project_payload(identity),
        "workflow_path": str(workflow_path) if workflow_path else None,
    }
    if workflow_path is None:
        base.update(
            {
                "status": "not_started",
                "current_phase": None,
                "next_eligible_phase": "preflight",
                "gates": {},
                "reconciliation": {"valid": True, "conflicts": []},
            }
        )
        return 0, base
    workflow = common.read_yaml(workflow_path)
    if not isinstance(workflow, dict):
        raise ValueError("workflow must be a JSON-compatible YAML mapping: {}".format(workflow_path))
    reconciliation = _reconcile_workflow(
        workflow,
        current_baseline=_current_baseline(args.project, identity),
        current_time=datetime.now(timezone.utc).isoformat(),
        manifest_conflicts=_manifest_conflicts(workflow_path, workflow),
        workflow_root=_workflow_root(workflow_path),
    )
    current, next_phase = _phase_summary(workflow, reconciliation)
    base.update(
        {
            "ok": reconciliation["valid"],
            "status": "active" if reconciliation["valid"] else "recovery_required",
            "current_phase": current,
            "next_eligible_phase": next_phase,
            "gates": workflow.get("gates", {}),
            "phases": workflow.get("phases", []),
            "evidence": workflow.get("evidence", []),
            "archive_confirmation": workflow.get("archive_confirmation"),
            "reconciliation": reconciliation,
        }
    )
    return (0 if reconciliation["valid"] else 1), base


def _entry_check(args):
    """Report entry eligibility without initializing or transitioning workflow state."""

    installed_skills_root = Path(__file__).resolve().parents[2]
    preflight_report = preflight.run_preflight(
        skill_roots=(installed_skills_root,),
        check_harness_entries=True,
        invoking_entry=args.entry,
    )
    _, status_report = _status(args)
    decision = entry_contract.evaluate_entry_request(
        args.entry,
        status_report,
        status_report["reconciliation"],
        requested_scope=tuple(args.requested_scope),
    )
    installation = preflight_report["harness_installation"]
    if not preflight_report["entry_ready"]:
        incompatible = list(installation["incompatible_entries"])
        decision["eligible"] = False
        decision["reason_code"] = (
            "harness_contract_incompatible"
            if incompatible or (
                installation["core_path"]
                and not installation["contract_compatible"]
            )
            else "harness_installation_incomplete"
        )
        decision["missing_prerequisites"] = list(dict.fromkeys(
            list(decision["missing_prerequisites"])
            + list(installation["missing_entries"])
            + incompatible
        ))
        decision["forbidden_scope"] = list(dict.fromkeys(
            list(decision["forbidden_scope"]) + list(decision["allowed_scope"])
        ))
        decision["allowed_scope"] = []
        decision["recommended_entry"] = None
    diagnostic_entries = {"grill-harness", "grh-upstream-check"}
    missing_required = list(preflight_report["missing_required"])
    if missing_required and args.entry == "grh-learn":
        dependency_free_operations = {"search_knowledge"}
        dependency_blocked = [
            operation for operation in decision["allowed_scope"]
            if operation not in dependency_free_operations
        ]
        dependency_free = [
            operation for operation in decision["allowed_scope"]
            if operation in dependency_free_operations
        ]
        decision["missing_prerequisites"] = list(dict.fromkeys(
            list(decision["missing_prerequisites"]) + missing_required
        ))
        decision["forbidden_scope"] = list(dict.fromkeys(
            list(decision["forbidden_scope"]) + dependency_blocked
        ))
        decision["allowed_scope"] = dependency_free
        if decision["eligible"] and dependency_free:
            decision["reason_code"] = "eligible_with_restricted_scope"
        elif not dependency_free:
            was_eligible = decision["eligible"]
            decision["eligible"] = False
            if was_eligible:
                decision["reason_code"] = "missing_required_capabilities"
                decision["recommended_entry"] = None
    elif missing_required and args.entry not in diagnostic_entries:
        was_eligible = decision["eligible"]
        decision["eligible"] = False
        if was_eligible:
            decision["reason_code"] = "missing_required_capabilities"
            decision["recommended_entry"] = None
        decision["missing_prerequisites"] = list(dict.fromkeys(
            list(decision["missing_prerequisites"]) + missing_required
        ))
        decision["forbidden_scope"] = list(dict.fromkeys(
            list(decision["forbidden_scope"]) + list(decision["allowed_scope"])
        ))
        decision["allowed_scope"] = []
    control = entry_contract.entry_control_summary(args.entry, status_report, decision)
    return (0 if decision["eligible"] else 1), {
        "ok": decision["eligible"],
        "command": "entry-check",
        "project": status_report["project"],
        "workflow_path": status_report["workflow_path"],
        "preflight": preflight_report,
        "status": status_report,
        "decision": decision,
        "control": control,
    }


def _upstream_check(args):
    default_manifest = Path(__file__).resolve().parent.parent / "references" / "上游清单.yaml"
    previous_path = (
        Path(args.previous).expanduser().resolve()
        if args.previous
        else default_manifest
    )
    previous = common.read_yaml(previous_path)
    if not isinstance(previous, dict):
        raise ValueError("upstream manifest must be a JSON-compatible YAML mapping")
    upstream_check.validate_manifest(previous)
    facts = None
    if args.facts:
        facts = common.read_yaml(Path(args.facts).expanduser().resolve())
        if not isinstance(facts, dict):
            raise ValueError("upstream facts must be a JSON-compatible YAML mapping")
    if args.offline and facts is None:
        raise ValueError("offline upstream check requires --facts")
    report = upstream_check.check_upstream(
        previous,
        facts or {},
        offline=args.offline,
        remote_loader=(
            None
            if args.offline
            else lambda: upstream_check.load_remote_facts(previous)
        ),
        checked_at=args.checked_at,
    )
    return 0, {"ok": True, "command": "upstream-check", "upstream": report}


def _migrate(args):
    report = migration.migrate_workflow(args.workflow, checked_at=args.checked_at)
    return 0, {"ok": True, "command": "migrate", "migration": report}


def _rollback(args):
    report = migration.rollback_migration(args.report)
    return 0, {"ok": True, "command": "rollback", "rollback": report}


def _record(args):
    baseline = None
    if args.project:
        identity = _identity_for_stored_project(
            state.identify_project(Path(args.project))
        )
        workflow_state = common.read_yaml(_workflow_file(args.workflow))
        if (
            not isinstance(workflow_state, Mapping)
            or workflow_state.get("project_id") != identity.project_id
        ):
            raise ValueError("project does not own the selected workflow")
        baseline = _current_baseline(args.project, identity)
    report = workflow_ops.register_record(
        args.workflow,
        args.kind,
        args.record,
        current_baseline=baseline,
        project_root=args.project,
    )
    return 0, {"ok": True, "command": "record", "record": report}


def _approve(args):
    versions = workflow_ops.parse_artifact_versions(args.artifact_version)
    report = workflow_ops.approve_gate(
        args.workflow, args.gate, args.approval_id, versions
    )
    return 0, {"ok": True, "command": "approve", "approval": report}


def _transition(args):
    report = workflow_ops.transition_phase(
        args.workflow,
        args.phase,
        args.target,
        artifacts=args.artifact,
        evidence=args.evidence,
        skip_reason=args.skip_reason,
        skip_approval_id=args.skip_approval_id,
    )
    return 0, {"ok": True, "command": "transition", "transition": report}


def _task_transition(args):
    identity = _identity_for_stored_project(
        state.identify_project(Path(args.project))
    )
    workflow_state = common.read_yaml(_workflow_file(args.workflow))
    if (
        not isinstance(workflow_state, Mapping)
        or workflow_state.get("project_id") != identity.project_id
    ):
        raise ValueError("project does not own the selected workflow")
    baseline = _current_baseline(args.project, identity)
    report = workflow_ops.transition_task(
        args.workflow,
        args.task,
        args.target,
        evidence=args.evidence,
        current_baseline=baseline,
    )
    return 0, {
        "ok": True,
        "command": "task-transition",
        "task_transition": report,
    }


def _parser():
    parser = MachineJsonArgumentParser(prog="grh.py")
    commands = parser.add_subparsers(dest="command", required=True)

    identify = commands.add_parser("identify")
    identify.add_argument("--project", required=True)
    identify.set_defaults(handler=_identify)

    preflight_command = commands.add_parser("preflight")
    preflight_command.add_argument("--skill-root", action="append", default=[])
    preflight_command.set_defaults(handler=_preflight)

    init = commands.add_parser("init")
    init.add_argument("--project", required=True)
    init.add_argument("--workflow-name", required=True)
    init.add_argument("--workflow-key")
    init.add_argument("--created-date", required=True)
    init.set_defaults(handler=_init)

    status = commands.add_parser("status")
    status.add_argument("--project", required=True)
    status.add_argument("--workflow")
    status.set_defaults(handler=_status)

    entry_check = commands.add_parser("entry-check")
    entry_check.add_argument("--entry", choices=sorted(entry_contract.PUBLIC_ENTRIES), required=True)
    entry_check.add_argument("--project", required=True)
    entry_check.add_argument("--workflow")
    entry_check.add_argument("--requested-scope", action="append", default=[])
    entry_check.set_defaults(handler=_entry_check)

    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--workflow", required=True)
    reconcile.add_argument("--project")
    reconcile.set_defaults(handler=_reconcile)

    upstream = commands.add_parser("upstream-check")
    upstream.add_argument("--previous")
    upstream.add_argument("--facts")
    upstream.add_argument("--checked-at", required=True)
    upstream.add_argument("--offline", action="store_true")
    upstream.set_defaults(handler=_upstream_check)

    migrate = commands.add_parser("migrate")
    migrate.add_argument("--workflow", required=True)
    migrate.add_argument("--checked-at")
    migrate.set_defaults(handler=_migrate)

    rollback = commands.add_parser("rollback")
    rollback.add_argument("--report", required=True)
    rollback.set_defaults(handler=_rollback)

    record = commands.add_parser("record")
    record.add_argument("--workflow", required=True)
    record.add_argument("--kind", choices=sorted(workflow_ops.KINDS), required=True)
    record.add_argument("--record", required=True)
    record.add_argument("--project")
    record.set_defaults(handler=_record)

    approve = commands.add_parser("approve")
    approve.add_argument("--workflow", required=True)
    approve.add_argument("--gate", choices=state.HUMAN_GATES, required=True)
    approve.add_argument("--approval-id", required=True)
    approve.add_argument("--artifact-version", action="append", default=[], required=True)
    approve.set_defaults(handler=_approve)

    transition = commands.add_parser("transition")
    transition.add_argument("--workflow", required=True)
    transition.add_argument("--phase", choices=state.WORKFLOW_PHASES, required=True)
    transition.add_argument("--to", dest="target", choices=state.WORKFLOW_STATES, required=True)
    transition.add_argument("--artifact", action="append")
    transition.add_argument("--evidence", action="append")
    transition.add_argument("--skip-reason")
    transition.add_argument("--skip-approval-id")
    transition.set_defaults(handler=_transition)

    task_transition = commands.add_parser("task-transition")
    task_transition.add_argument("--workflow", required=True)
    task_transition.add_argument("--task", required=True)
    task_transition.add_argument("--to", dest="target", choices=state.WORKFLOW_STATES, required=True)
    task_transition.add_argument("--evidence", action="append")
    task_transition.add_argument("--project", required=True)
    task_transition.set_defaults(handler=_task_transition)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        exit_code, payload = args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        message = (
            "操作失败：{}。当前操作未完成，系统不会自动安装、更新、覆盖文件"
            "或推进工作流；请修复上述输入、状态或环境冲突后重试。"
        ).format(error)
        _emit(
            {
                "ok": False,
                "command": args.command,
                "error": {"type": type(error).__name__, "message": message},
            }
        )
        return 2
    _emit(payload)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
