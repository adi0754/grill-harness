"""Versioned, backed-up migration for Grill Harness machine files."""

import copy
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import common
import failure_control


FILES = {
    "state.yaml": "state",
    "artifacts.yaml": "artifacts",
    "tasks.yaml": "tasks",
    "evidence.yaml": "evidence",
    "failures.yaml": "failure_attempts",
}
CURRENT_SCHEMA_VERSION = 1
CURRENT_WORKFLOW_VERSION = 1
TRANSACTION_FILE = ".migration-transaction.yaml"


def _state_path(value):
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        nested = path / "系统" / "state.yaml"
        path = nested if nested.is_file() else path / "state.yaml"
    return path


def _system_directory(value):
    state_path = _state_path(value)
    try:
        state_path.relative_to(common.resolve_storage_root())
    except ValueError:
        raise ValueError("migration is only allowed under ~/.grill-harness storage")
    return state_path.parent


def _valid_approval_version(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _matches_existing_snapshot(snapshot, candidate):
    if not _valid_approval_version(candidate.get("version")):
        return False
    candidate_hash = failure_control.approval_record_hash(candidate)
    return (
        snapshot.get("approval_version") is None
        or snapshot.get("approval_version") == candidate.get("version")
    ) and (
        snapshot.get("approval_hash") is None
        or snapshot.get("approval_hash") == candidate_hash
    )


def _hydrate_failure_approval_snapshots(record, ledger):
    override = record.get("threshold_override")
    if (
        record.get("threshold") != failure_control.DEFAULT_ATTEMPT_THRESHOLD
        and isinstance(override, dict)
        and (
            override.get("approval_version") is None
            or override.get("approval_hash") is None
        )
    ):
        matches = []
        for candidate in ledger:
            if not isinstance(candidate, dict) or candidate.get("id") != override.get(
                "approval_id"
            ) or not _matches_existing_snapshot(override, candidate):
                continue
            candidate_override = dict(
                override,
                threshold=record.get("threshold"),
                approval_version=candidate.get("version"),
                approval_hash=failure_control.approval_record_hash(candidate),
            )
            report = failure_control.validate_threshold_override(
                candidate_override,
                [candidate],
                fingerprint=record.get("fingerprint"),
                issue_id=record.get("issue_id"),
            )
            if report["valid"]:
                matches.append(candidate)
        if len(matches) != 1:
            raise ValueError(
                "legacy threshold approval cannot be resolved uniquely; reconcile is required"
            )
        override["approval_version"] = matches[0].get("version")
        override["approval_hash"] = failure_control.approval_record_hash(matches[0])

    new_chain = record.get("new_chain_approval")
    if isinstance(new_chain, dict) and (
        new_chain.get("approval_version") is None
        or new_chain.get("approval_hash") is None
    ):
        reason = new_chain.get("reason")
        matches = [
            candidate
            for candidate in ledger
            if isinstance(candidate, dict)
            and _matches_existing_snapshot(new_chain, candidate)
            and failure_control.matches_new_chain_approval(
                candidate,
                approval_id=new_chain.get("approval_id"),
                fingerprint=record.get("fingerprint"),
                issue_id=record.get("issue_id"),
                failure_class=record.get("failure_class"),
                originating_baseline=record.get(
                    "originating_baseline", record.get("git_baseline")
                ),
                reason=reason,
            )
        ]
        if len(matches) != 1:
            raise ValueError(
                "legacy new-chain approval cannot be resolved uniquely; reconcile is required"
            )
        new_chain["approval_version"] = matches[0].get("version")
        new_chain["approval_hash"] = failure_control.approval_record_hash(matches[0])


def _hydrate_repair_approval_snapshots(state_payload, tasks_manifest):
    state_tasks = state_payload.get("tasks")
    manifest_tasks = tasks_manifest.get("tasks")
    if not isinstance(state_tasks, list) or state_tasks != manifest_tasks:
        return
    ledger = state_payload.get("ledger", ())
    failure_records = state_payload.get("failure_attempts", ())
    for task in state_tasks:
        if not isinstance(task, dict) or not (
            task.get("task_type") == "repair"
            or task.get("kind") == "repair"
            or task.get("failure_fingerprint") is not None
        ):
            continue
        repair_mode = task.get("repair_mode")
        if repair_mode == "ordinary" or repair_mode not in {
            "recovery",
            "route_selection",
            "reconcile",
        }:
            continue
        if (
            task.get("repair_approval_version") is not None
            and task.get("repair_approval_hash") is not None
        ):
            continue
        fingerprint = task.get("failure_fingerprint", task.get("fingerprint"))
        issue_ids = {
            record.get("issue_id")
            for record in failure_records
            if isinstance(record, dict)
            and record.get("fingerprint") == fingerprint
            and isinstance(record.get("issue_id"), str)
            and record.get("issue_id").strip()
        }
        if len(issue_ids) != 1:
            raise ValueError(
                "legacy repair approval cannot resolve its failure issue; reconcile is required"
            )
        approval_id = task.get(
            "repair_approval_id",
            task.get(
                "{}_approval_id".format(repair_mode),
                task.get("route_approval_id")
                if repair_mode == "route_selection"
                else None,
            ),
        )
        matches = [
            candidate
            for candidate in ledger
            if isinstance(candidate, dict)
            and _matches_existing_snapshot(
                {
                    "approval_version": task.get("repair_approval_version"),
                    "approval_hash": task.get("repair_approval_hash"),
                },
                candidate,
            )
            and failure_control.matches_repair_approval(
                candidate,
                approval_id=approval_id,
                repair_mode=repair_mode,
                fingerprint=fingerprint,
                issue_id=next(iter(issue_ids)),
            )
        ]
        if len(matches) != 1:
            raise ValueError(
                "legacy repair approval cannot be resolved uniquely; reconcile is required"
            )
        task["repair_approval_version"] = matches[0].get("version")
        task["repair_approval_hash"] = failure_control.approval_record_hash(matches[0])
    tasks_manifest["tasks"] = copy.deepcopy(state_tasks)


def _hydrate_and_seal_failure_records(records, ledger):
    sealed = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("legacy failure attempt must be a mapping")
        clean = {
            key: value
            for key, value in record.items()
            if key not in {"predecessor_hash", "record_hash"}
        }
        _hydrate_failure_approval_snapshots(clean, ledger)
        sealed.append(
            failure_control.seal_failure_record(
                clean, sealed[-1]["record_hash"] if sealed else None
            )
        )
    return sealed


def _load_bundle(value):
    system = _system_directory(value)
    payloads = {}
    for filename in FILES:
        path = system / filename
        if filename == "failures.yaml" and not path.is_file():
            continue
        payload = common.read_yaml(path)
        if not isinstance(payload, dict):
            raise ValueError("machine file must be a mapping: {}".format(path))
        payloads[filename] = payload
    state_payload = payloads.get("state.yaml")
    if not isinstance(state_payload, dict):
        raise ValueError("state must exist before migration")
    records = state_payload.get("failure_attempts", [])
    if not isinstance(records, list):
        raise ValueError("legacy failure_attempts must be a list")
    ledger = state_payload.get("ledger", ())
    if "failures.yaml" not in payloads:
        sealed = _hydrate_and_seal_failure_records(records, ledger)
        report = failure_control.validate_failure_chain(
            sealed, ledger=ledger
        )
        if not report["valid"]:
            raise ValueError(report["conflicts"][0]["conflict"])
        state_payload["failure_attempts"] = sealed
        failure_manifest = failure_control.failure_chain_manifest(
            sealed, integrity_origin="migration"
        )
        failure_manifest["schema_version"] = state_payload.get("schema_version", 0)
        failure_manifest["workflow_version"] = state_payload.get("workflow_version", 0)
        failure_manifest["_synthesized_missing"] = True
        payloads["failures.yaml"] = failure_manifest
    elif state_payload.get("workflow_version", 0) == 0:
        failure_manifest = payloads["failures.yaml"]
        manifest_records = failure_manifest.get("failure_attempts")
        if isinstance(manifest_records, list) and manifest_records == records:
            sealed = _hydrate_and_seal_failure_records(records, ledger)
            state_payload["failure_attempts"] = sealed
            failure_manifest["failure_attempts"] = copy.deepcopy(sealed)
            failure_manifest["count"] = len(sealed)
            failure_manifest["head"] = (
                sealed[-1].get("record_hash") if sealed else None
            )
    tasks_manifest = payloads.get("tasks.yaml")
    if isinstance(tasks_manifest, dict):
        _hydrate_repair_approval_snapshots(state_payload, tasks_manifest)
    return system, payloads


def _validate_bundle(payloads):
    state_payload = payloads["state.yaml"]
    for filename, field in (
        ("artifacts.yaml", "artifacts"),
        ("tasks.yaml", "tasks"),
        ("evidence.yaml", "evidence"),
        ("failures.yaml", "failure_attempts"),
    ):
        state_records = state_payload.get(field)
        manifest_records = payloads[filename].get(field)
        if not isinstance(state_records, list) or not isinstance(manifest_records, list):
            raise ValueError("{} records must be lists".format(field))
        if state_records != manifest_records:
            raise ValueError("{} manifest contradicts state".format(field))
    failure_report = failure_control.validate_failure_chain(
        state_payload.get("failure_attempts", ()),
        payloads["failures.yaml"],
        ledger=state_payload.get("ledger", ()),
    )
    if not failure_report["valid"]:
        raise ValueError(failure_report["conflicts"][0]["conflict"])


def _restore_interrupted(system):
    journal_path = system / TRANSACTION_FILE
    journal = common.read_yaml(journal_path)
    if journal is None:
        return False
    if not isinstance(journal, dict) or not isinstance(journal.get("backups"), dict):
        raise ValueError("migration transaction journal is corrupt")
    for filename in FILES:
        backup_value = journal["backups"].get(filename)
        if backup_value is None:
            continue
        backup = Path(backup_value)
        if not backup.is_file():
            raise ValueError("migration transaction backup is missing: {}".format(backup))
    for filename in FILES:
        backup_value = journal["backups"].get(filename)
        if backup_value is None:
            (system / filename).unlink(missing_ok=True)
        else:
            shutil.copy2(backup_value, str(system / filename))
    journal_path.unlink()
    return True


def migrate_workflow(value, checked_at=None):
    system = _system_directory(value)
    with common.exclusive_directory_lock(system / ".workflow.lock"):
        return _migrate_locked(system, checked_at)


def _migrate_locked(system, checked_at=None):
    _restore_interrupted(system)
    failure_manifest_existed = (system / "failures.yaml").is_file()
    _, payloads = _load_bundle(system / "state.yaml")
    _validate_bundle(payloads)
    versions = {
        int(payload.get("workflow_version", 0))
        for payload in payloads.values()
        if not isinstance(payload.get("workflow_version", 0), bool)
    }
    if len(versions) != 1:
        raise ValueError("machine files have inconsistent workflow versions")
    source_version = versions.pop()
    if source_version > CURRENT_WORKFLOW_VERSION:
        raise ValueError("workflow version is newer than this skill")
    if source_version == CURRENT_WORKFLOW_VERSION and all(
        payload.get("schema_version") == CURRENT_SCHEMA_VERSION
        for payload in payloads.values()
    ) and isinstance(payloads["state.yaml"].get("ledger"), list) and failure_manifest_existed:
        return {
            "changed": False,
            "from_version": source_version,
            "to_version": CURRENT_WORKFLOW_VERSION,
            "report_path": None,
        }
    if source_version not in (0, CURRENT_WORKFLOW_VERSION):
        raise ValueError("no migration path from workflow version {}".format(source_version))

    migrated = {}
    for filename, payload in payloads.items():
        updated = copy.deepcopy(payload)
        updated.pop("_synthesized_missing", None)
        updated["schema_version"] = CURRENT_SCHEMA_VERSION
        updated["workflow_version"] = CURRENT_WORKFLOW_VERSION
        if filename == "state.yaml":
            updated.setdefault("ledger", [])
        migrated[filename] = updated
    _validate_bundle(migrated)

    timestamp = checked_at or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    safe_timestamp = re.sub(r"[^0-9A-Za-z_.-]+", "_", timestamp)
    backup_directory = system / "备份" / (
        "{}-{}".format(safe_timestamp, uuid.uuid4().hex[:8])
    )
    report_directory = system / "迁移报告"
    temporary = Path(tempfile.mkdtemp(prefix=".migration-", dir=str(system)))
    backups = {}
    try:
        for filename, payload in migrated.items():
            common.atomic_write_yaml(temporary / filename, payload)
        _, verified = _load_bundle(temporary / "state.yaml")
        _validate_bundle(verified)

        backup_directory.mkdir(parents=True, exist_ok=False)
        for filename in FILES:
            source = system / filename
            if source.is_file():
                backup = backup_directory / filename
                shutil.copy2(str(source), str(backup))
                backups[filename] = str(backup)
            else:
                backups[filename] = None
        journal_path = system / TRANSACTION_FILE
        common.atomic_write_yaml(
            journal_path,
            {
                "operation": "migrate",
                "backups": backups,
                "target_version": CURRENT_WORKFLOW_VERSION,
            },
        )
        try:
            for filename in FILES:
                os.replace(str(temporary / filename), str(system / filename))
        except OSError:
            for filename, backup in backups.items():
                if backup is None:
                    (system / filename).unlink(missing_ok=True)
                else:
                    shutil.copy2(backup, str(system / filename))
            journal_path.unlink(missing_ok=True)
            raise
        report = {
            "schema_version": 1,
            "changed": True,
            "from_version": source_version,
            "to_version": CURRENT_WORKFLOW_VERSION,
            "checked_at": timestamp,
            "backups": backups,
            "unknown_fields_preserved": True,
        }
        report_directory.mkdir(parents=True, exist_ok=True)
        report_path = report_directory / (
            "迁移-{}-{}.yaml".format(safe_timestamp, uuid.uuid4().hex[:8])
        )
        common.atomic_write_yaml(report_path, report)
        journal_path.unlink(missing_ok=True)
        report["report_path"] = str(report_path)
        return report
    finally:
        shutil.rmtree(str(temporary), ignore_errors=True)


def rollback_migration(report_value):
    report_path = Path(report_value).expanduser().resolve()
    try:
        report_path.relative_to(common.resolve_storage_root())
    except ValueError:
        raise ValueError("rollback is only allowed under ~/.grill-harness storage")
    system = report_path.parent.parent
    with common.exclusive_directory_lock(system / ".workflow.lock"):
        return _rollback_locked(report_path, system)


def _rollback_locked(report_path, system):
    _restore_interrupted(system)
    report = common.read_yaml(report_path)
    if not isinstance(report, dict) or not isinstance(report.get("backups"), dict):
        raise ValueError("migration report has no usable backups")
    restored = []
    for filename in FILES:
        backup_value = report["backups"].get(filename)
        if backup_value is None:
            continue
        backup = Path(backup_value)
        if not backup.is_file():
            raise ValueError("migration backup is missing: {}".format(backup))
    rollback_backup_directory = system / "备份" / (
        "rollback-{}".format(uuid.uuid4().hex[:8])
    )
    rollback_backup_directory.mkdir(parents=True, exist_ok=False)
    current_backups = {}
    for filename in FILES:
        current_backup = rollback_backup_directory / filename
        shutil.copy2(str(system / filename), str(current_backup))
        current_backups[filename] = str(current_backup)
    journal_path = system / TRANSACTION_FILE
    common.atomic_write_yaml(
        journal_path,
        {"operation": "rollback", "backups": current_backups},
    )
    try:
        for filename in FILES:
            backup_value = report["backups"].get(filename)
            if backup_value is None:
                (system / filename).unlink(missing_ok=True)
            else:
                backup = Path(backup_value)
                shutil.copy2(str(backup), str(system / filename))
            restored.append(str(system / filename))
    except OSError:
        for filename, backup in current_backups.items():
            shutil.copy2(backup, str(system / filename))
        journal_path.unlink(missing_ok=True)
        raise
    journal_path.unlink(missing_ok=True)
    return {"rolled_back": True, "report_path": str(report_path), "restored": restored}


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "CURRENT_WORKFLOW_VERSION",
    "migrate_workflow",
    "rollback_migration",
]
