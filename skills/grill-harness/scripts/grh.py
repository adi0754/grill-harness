#!/usr/bin/env python3
"""Read-only machine JSON entry point for Grill Harness."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import common
import preflight
import state
import upstream_check
import validate


TERMINAL_PHASE_STATES = {"completed", "skipped", "superseded", "cancelled"}


def _emit(payload):
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _project_payload(project):
    payload = asdict(project)
    payload["history_roots"] = list(payload["history_roots"])
    payload["relocation_candidates"] = list(payload["relocation_candidates"])
    return payload


def _workflow_file(path):
    source = Path(path).expanduser().resolve()
    return source / "state.yaml" if source.is_dir() else source


def _discover_workflow(identity):
    workflows = (
        common.resolve_storage_root()
        / common.STORAGE_DIRECTORIES["projects"]
        / identity.directory_name
        / "工作流"
    )
    candidates = sorted(workflows.glob("*/state.yaml")) if workflows.is_dir() else []
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


def _reconcile(args):
    workflow_path = _workflow_file(args.workflow)
    workflow = common.read_yaml(workflow_path)
    if not isinstance(workflow, dict):
        raise ValueError("workflow must be a JSON-compatible YAML mapping: {}".format(workflow_path))
    report = validate.reconcile_workflow(workflow)
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
    reconciliation = validate.reconcile_workflow(workflow)
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
    parser = argparse.ArgumentParser(prog="grh.py")
    commands = parser.add_subparsers(dest="command", required=True)

    identify = commands.add_parser("identify")
    identify.add_argument("--project", required=True)
    identify.set_defaults(handler=_identify)

    preflight_command = commands.add_parser("preflight")
    preflight_command.add_argument("--skill-root", action="append", default=[])
    preflight_command.set_defaults(handler=_preflight)

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
