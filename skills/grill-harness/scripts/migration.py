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


FILES = {
    "state.yaml": "state",
    "artifacts.yaml": "artifacts",
    "tasks.yaml": "tasks",
    "evidence.yaml": "evidence",
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


def _load_bundle(value):
    system = _system_directory(value)
    payloads = {}
    for filename in FILES:
        path = system / filename
        payload = common.read_yaml(path)
        if not isinstance(payload, dict):
            raise ValueError("machine file must be a mapping: {}".format(path))
        payloads[filename] = payload
    return system, payloads


def _validate_bundle(payloads):
    state_payload = payloads["state.yaml"]
    for filename, field in (
        ("artifacts.yaml", "artifacts"),
        ("tasks.yaml", "tasks"),
        ("evidence.yaml", "evidence"),
    ):
        state_records = state_payload.get(field)
        manifest_records = payloads[filename].get(field)
        if not isinstance(state_records, list) or not isinstance(manifest_records, list):
            raise ValueError("{} records must be lists".format(field))
        if state_records != manifest_records:
            raise ValueError("{} manifest contradicts state".format(field))


def _restore_interrupted(system):
    journal_path = system / TRANSACTION_FILE
    journal = common.read_yaml(journal_path)
    if journal is None:
        return False
    if not isinstance(journal, dict) or not isinstance(journal.get("backups"), dict):
        raise ValueError("migration transaction journal is corrupt")
    for filename in FILES:
        backup = Path(journal["backups"].get(filename, ""))
        if not backup.is_file():
            raise ValueError("migration transaction backup is missing: {}".format(backup))
    for filename in FILES:
        shutil.copy2(journal["backups"][filename], str(system / filename))
    journal_path.unlink()
    return True


def migrate_workflow(value, checked_at=None):
    system = _system_directory(value)
    with common.exclusive_directory_lock(system / ".workflow.lock"):
        return _migrate_locked(system, checked_at)


def _migrate_locked(system, checked_at=None):
    _restore_interrupted(system)
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
    ) and isinstance(payloads["state.yaml"].get("ledger"), list):
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
            backup = backup_directory / filename
            shutil.copy2(str(source), str(backup))
            backups[filename] = str(backup)
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
        backup = Path(report["backups"].get(filename, ""))
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
            backup = Path(report["backups"][filename])
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
