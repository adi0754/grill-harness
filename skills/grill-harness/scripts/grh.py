#!/usr/bin/env python3
"""Read-only machine JSON entry point for Grill Harness."""

import argparse
import json
import shutil
import sys
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from pathlib import Path

import common
import preflight
import state
import upstream_check
import validate


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
                "error": {"type": "usage", "message": message},
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


def _discover_workflow(identity):
    workflows = (
        common.resolve_storage_root()
        / common.STORAGE_DIRECTORIES["projects"]
        / identity.directory_name
        / "工作流"
    )
    candidates = sorted(workflows.glob("*/系统/state.yaml")) if workflows.is_dir() else []
    if len(candidates) > 1:
        raise ValueError(
            "multiple workflows found; pass --workflow: {}".format(
                ", ".join(str(path) for path in candidates)
            )
        )
    return candidates[0] if candidates else None


def _phase_summary(workflow, reconciliation):
    phases = {
        item.get("id"): item
        for item in workflow.get("phases", ())
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


def _reconcile_workflow(workflow):
    report = validate.reconcile_workflow(workflow)
    conflicts = list(report.get("conflicts", ()))
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
    for phase in workflow.get("phases", ()):
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
    return {"valid": not conflicts, "conflicts": conflicts}


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
    for field in ("phases", "artifacts", "tasks", "evidence"):
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
        if not isinstance(payload.get(field), list):
            raise ValueError("{} manifest {} must be a list: {}".format(field, field, path))


def _initialize_workflow(identity, workflow_name, workflow_key, created_on):
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
            "gates": {},
        },
        "artifacts.yaml": {"artifacts": []},
        "tasks.yaml": {"tasks": []},
        "evidence.yaml": {"evidence": []},
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
    if project_info_path.exists() and _read_mapping(project_info_path, "project info") != project_record:
        raise ValueError("project info conflicts with identified project: {}".format(project_info_path))

    if project_index_path.exists():
        project_index = _read_mapping(project_index_path, "project index")
        projects = project_index.get("projects")
        if not isinstance(projects, list):
            raise ValueError("project index projects must be a list: {}".format(project_index_path))
        matching = [item for item in projects if isinstance(item, dict) and item.get("project_id") == identity.project_id]
        if matching and matching != [project_record]:
            raise ValueError("project index conflicts with identified project: {}".format(project_index_path))
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
            temporary.rename(workflow_directory)
        finally:
            if temporary.exists():
                shutil.rmtree(str(temporary))
        created = True

    if not project_info_path.exists():
        common.atomic_write_yaml(project_info_path, project_record)
    if not matching:
        updated_index = dict(project_index)
        updated_index["projects"] = list(projects) + [project_record]
        common.atomic_write_yaml(project_index_path, updated_index)
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
    identity = state.identify_project(Path(args.project))
    created, workflow_identifier, workflow_path = _initialize_workflow(
        identity,
        workflow_name,
        workflow_key,
        created_on,
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
    report = _reconcile_workflow(workflow)
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
    reconciliation = _reconcile_workflow(workflow)
    current, next_phase = _phase_summary(workflow, reconciliation)
    base.update(
        {
            "ok": reconciliation["valid"],
            "status": "active" if reconciliation["valid"] else "recovery_required",
            "current_phase": current,
            "next_eligible_phase": next_phase,
            "gates": workflow.get("gates", {}),
            "reconciliation": reconciliation,
        }
    )
    return (0 if reconciliation["valid"] else 1), base


def _upstream_check(args):
    previous = common.read_yaml(Path(args.previous).expanduser().resolve())
    facts = common.read_yaml(Path(args.facts).expanduser().resolve())
    if not isinstance(previous, dict) or not isinstance(facts, dict):
        raise ValueError("upstream inputs must be JSON-compatible YAML mappings")
    report = upstream_check.check_upstream(
        previous,
        facts,
        offline=args.offline,
        checked_at=args.checked_at,
    )
    return 0, {"ok": True, "command": "upstream-check", "upstream": report}


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

    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--workflow", required=True)
    reconcile.set_defaults(handler=_reconcile)

    upstream = commands.add_parser("upstream-check")
    upstream.add_argument("--previous", required=True)
    upstream.add_argument("--facts", required=True)
    upstream.add_argument("--checked-at", required=True)
    upstream.add_argument("--offline", action="store_true")
    upstream.set_defaults(handler=_upstream_check)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        exit_code, payload = args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _emit(
            {
                "ok": False,
                "command": args.command,
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        )
        return 2
    _emit(payload)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
