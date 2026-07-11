"""Project and workflow identity for Grill Harness storage."""

import copy
import hashlib
import json
import ntpath
import os
import posixpath
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit


SHORT_ID_LENGTH = 12

WORKFLOW_STATES = (
    "pending",
    "in_progress",
    "needs_user",
    "blocked",
    "completed",
    "stale",
    "superseded",
    "skipped",
    "failed",
    "cancelled",
)
STATES = WORKFLOW_STATES

LEGAL_TRANSITIONS = {
    "pending": frozenset(
        ("in_progress", "stale", "skipped", "cancelled", "superseded")
    ),
    "in_progress": frozenset(
        (
            "needs_user",
            "blocked",
            "completed",
            "failed",
            "cancelled",
            "stale",
            "superseded",
        )
    ),
    "needs_user": frozenset(
        ("in_progress", "blocked", "cancelled", "stale", "superseded")
    ),
    "blocked": frozenset(
        ("in_progress", "failed", "cancelled", "stale", "superseded")
    ),
    "completed": frozenset(("stale", "superseded")),
    "stale": frozenset(("in_progress", "superseded", "cancelled")),
    "superseded": frozenset(),
    "skipped": frozenset(("stale", "superseded")),
    "failed": frozenset(("in_progress", "cancelled", "superseded")),
    "cancelled": frozenset(),
}

HUMAN_GATES = (
    "requirements_baseline",
    "route_selection",
    "final_spec_approval",
)

PHASE_GATE_REQUIREMENTS = {
    "design": "requirements_baseline",
    "repository_challenge": "route_selection",
    "specification": "route_selection",
    "tasking": "final_spec_approval",
    "implementation": "final_spec_approval",
}

LEDGER_RECORD_TYPES = (
    "REQ",
    "DEC",
    "CON",
    "RISK",
    "CHG",
    "TASK",
    "ISSUE",
    "EVD",
)


class StateContractError(ValueError):
    """Raised when workflow state contradicts the workflow contract."""


class InvalidTransition(StateContractError):
    """Raised when a workflow state transition is not legal."""


class LedgerContractError(ValueError):
    """Raised when a ledger record would lose stable history."""


def _require_known_state(value: str) -> None:
    if value not in LEGAL_TRANSITIONS:
        raise ValueError("unknown workflow state: {!r}".format(value))


def can_transition(source: str, target: str) -> bool:
    """Return whether an explicit, non-noop workflow transition is legal."""

    _require_known_state(source)
    _require_known_state(target)
    return target in LEGAL_TRANSITIONS[source]


def validate_transition(source: str, target: str) -> None:
    """Validate a transition without changing either state."""

    if not can_transition(source, target):
        raise InvalidTransition(
            "illegal workflow transition: {} -> {}".format(source, target)
        )


def transition_state(source: str, target: str) -> str:
    """Validate and return the target state for callers building new records."""

    validate_transition(source, target)
    return target


def validate_human_gate(gate: str, status: str) -> None:
    if gate not in HUMAN_GATES:
        raise StateContractError("unknown human gate: {!r}".format(gate))
    if status != "needs_user":
        raise StateContractError(
            "human gate {} must use needs_user status".format(gate)
        )


def validate_gate_contract(gate: str, record: Mapping[str, Any]) -> None:
    """Validate a durable approval bound to concrete artifact versions."""

    if gate not in HUMAN_GATES:
        raise StateContractError("unknown human gate: {!r}".format(gate))
    if record.get("status") != "approved":
        raise StateContractError("human gate {} is not approved".format(gate))
    approval_id = record.get("approval_id")
    if not isinstance(approval_id, str) or not re.fullmatch(
        r"(?:DEC|CHG)-[0-9]{3,}", approval_id
    ):
        raise StateContractError(
            "human gate {} requires a DEC or CHG approval id".format(gate)
        )
    artifact_versions = record.get("artifact_versions")
    if not isinstance(artifact_versions, Mapping) or not artifact_versions:
        raise StateContractError(
            "human gate {} requires at least one artifact version".format(gate)
        )
    for artifact_id, version in artifact_versions.items():
        if not isinstance(artifact_id, str) or not artifact_id:
            raise StateContractError("artifact version keys must be non-empty ids")
        _positive_integer(version, "artifact version")


def validate_phase_entry(
    phase_id: str, gates: Mapping[str, Mapping[str, Any]]
) -> None:
    """Reject downstream work until its required human checkpoint is approved."""

    required_gate = PHASE_GATE_REQUIREMENTS.get(phase_id)
    if required_gate is None:
        return
    gate_record = gates.get(required_gate)
    if gate_record is None:
        raise StateContractError("required human gate {} is missing".format(required_gate))
    validate_gate_contract(required_gate, gate_record)


def validate_phase(phase: Mapping[str, Any]) -> None:
    """Validate phase invariants that cannot be expressed by transitions alone."""

    status = phase.get("status")
    _require_known_state(status)
    if status == "completed":
        if not phase.get("artifacts"):
            raise StateContractError("completed phase requires at least one artifact")
        if not phase.get("evidence"):
            raise StateContractError(
                "completed phase requires at least one evidence record"
            )
    if status == "skipped":
        if phase.get("optional") is not True:
            raise StateContractError("only an optional phase may be skipped")
        reason = phase.get("skip_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise StateContractError("skipped phase requires a reason")


def _positive_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LedgerContractError("{} must be a positive integer".format(field_name))
    return value


def format_record_id(record_type: str, sequence: int) -> str:
    if record_type not in LEDGER_RECORD_TYPES:
        raise LedgerContractError(
            "unknown ledger record type: {!r}".format(record_type)
        )
    number = _positive_integer(sequence, "sequence")
    return "{}-{:03d}".format(record_type, number)


def _validate_record(record: Mapping[str, Any]) -> None:
    record_type = record.get("type")
    if record_type not in LEDGER_RECORD_TYPES:
        raise LedgerContractError(
            "unknown ledger record type: {!r}".format(record_type)
        )
    record_id = record.get("id")
    if not isinstance(record_id, str) or not re.fullmatch(
        r"{}-[0-9]{{3,}}".format(record_type), record_id
    ):
        raise LedgerContractError(
            "ledger id does not match its type: {!r}".format(record_id)
        )
    _positive_integer(record.get("version"), "version")


def create_ledger_record(
    record_type: str,
    sequence: int,
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    contents = {} if payload is None else copy.deepcopy(dict(payload))
    reserved = {"id", "type", "version"}.intersection(contents)
    if reserved:
        raise LedgerContractError(
            "payload cannot replace ledger identity fields: {}".format(
                ", ".join(sorted(reserved))
            )
        )
    contents.update(
        {
            "id": format_record_id(record_type, sequence),
            "type": record_type,
            "version": 1,
        }
    )
    return contents


def revise_ledger_record(
    record: Mapping[str, Any],
    changes: Mapping[str, Any],
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    _validate_record(record)
    if expected_version is not None:
        _positive_integer(expected_version, "expected version")
        if record["version"] != expected_version:
            raise LedgerContractError(
                "expected version {} but found {}".format(
                    expected_version, record["version"]
                )
            )
    reserved = {"id", "type", "version"}.intersection(changes)
    if reserved:
        raise LedgerContractError(
            "revision cannot replace ledger identity fields: {}".format(
                ", ".join(sorted(reserved))
            )
        )
    revised = copy.deepcopy(dict(record))
    revised.update(copy.deepcopy(dict(changes)))
    revised["version"] = record["version"] + 1
    return revised


def validate_ledger(records: Iterable[Mapping[str, Any]]) -> None:
    versions_by_id = {}
    for record in records:
        _validate_record(record)
        versions_by_id.setdefault(record["id"], []).append(record["version"])
    for record_id, versions in versions_by_id.items():
        ordered = sorted(versions)
        expected = list(range(1, len(ordered) + 1))
        if ordered != expected or len(ordered) != len(set(ordered)):
            raise LedgerContractError(
                "ledger versions for {} must be unique and contiguous from 1".format(
                    record_id
                )
            )


def validate_ledger_history(records: Sequence[Mapping[str, Any]]) -> None:
    validate_ledger(records)


revise_record = revise_ledger_record


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str
    directory_name: str
    normalized_path: str
    is_git: bool
    normalized_remote: Optional[str]
    history_roots: Tuple[str, ...]
    relocation_candidates: Tuple[str, ...]


def _looks_like_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:", value)) or _looks_like_unc_path(value)


def _looks_like_unc_path(value: str) -> bool:
    return value.startswith("\\\\") or value.startswith("//")


def normalize_project_path(path: Path) -> str:
    raw_path = os.fspath(path)
    if _looks_like_windows_path(raw_path):
        return ntpath.normcase(ntpath.normpath(raw_path))
    resolved = Path(path).expanduser().resolve()
    return os.path.normcase(os.path.normpath(str(resolved)))


def normalize_git_remote(
    remote: Optional[str],
    repository_root: Optional[Path] = None,
) -> Optional[str]:
    if not remote or not remote.strip():
        return None
    value = remote.strip()
    if _looks_like_unc_path(value):
        normalized = value.replace("\\", "/").lstrip("/")
        server, separator, network_path = normalized.partition("/")
        if separator:
            return _canonical_network_file_remote(server, network_path)
    if _looks_like_windows_path(value):
        normalized_path = _normalize_windows_local_remote(value, repository_root)
        return "file://{}".format(normalized_path)
    scp_match = re.match(r"^(?:[^@/]+@)?([^:/]+):(.+)$", value)
    if scp_match and "://" not in value:
        host = scp_match.group(1).lower()
        repository_path = scp_match.group(2)
        return _clean_remote_path(host, repository_path)

    parsed = urlsplit(value)
    if parsed.scheme and parsed.scheme != "file":
        host = (parsed.hostname or "").lower()
        if ":" in host and not host.startswith("["):
            host = "[{}]".format(host)
        default_ports = {"http": 80, "https": 443, "ssh": 22, "git": 9418}
        if parsed.port and parsed.port != default_ports.get(parsed.scheme.lower()):
            host = "{}:{}".format(host, parsed.port)
        return _clean_remote_path(host, unquote(parsed.path))
    if parsed.scheme == "file":
        file_path = unquote(parsed.path)
        if parsed.netloc:
            server = (parsed.hostname or parsed.netloc).lower()
            if server == "localhost":
                if re.match(r"^/[A-Za-z]:[\\/]", file_path):
                    file_path = file_path[1:]
                return "file://{}".format(normalize_project_path(file_path))
            return _canonical_network_file_remote(server, file_path)
        if re.match(r"^/[A-Za-z]:[\\/]", file_path):
            file_path = file_path[1:]
        return "file://{}".format(normalize_project_path(file_path))

    local_path = Path(value).expanduser()
    if not local_path.is_absolute() and repository_root is not None:
        local_path = Path(repository_root) / local_path
    return "file://{}".format(normalize_project_path(local_path))


def _normalize_windows_local_remote(
    value: str,
    repository_root: Optional[Path],
) -> str:
    drive, tail = ntpath.splitdrive(value)
    is_drive_relative = bool(drive) and not tail.startswith(("\\", "/"))
    if is_drive_relative and repository_root is not None:
        normalized_root = normalize_project_path(repository_root)
        root_drive, _ = ntpath.splitdrive(normalized_root)
        if root_drive.lower() == drive.lower():
            value = ntpath.join(normalized_root, tail)
    return ntpath.normcase(ntpath.normpath(value))


def _canonical_network_file_remote(server: str, network_path: str) -> str:
    segments = network_path.replace("\\", "/").strip("/").split("/")
    if not segments or not segments[0]:
        return "file://{}".format(server.lower())
    share = segments[0]
    remainder = []
    for segment in segments[1:]:
        if not segment or segment == ".":
            continue
        if segment == "..":
            if remainder:
                remainder.pop()
            continue
        remainder.append(segment)
    path = posixpath.join(share, *remainder)
    return "file://{}/{}".format(server.lower(), path)


def _clean_remote_path(host: str, repository_path: str) -> str:
    cleaned = repository_path.strip().strip("/")
    if cleaned.lower().endswith(".git"):
        cleaned = cleaned[:-4]
    return "{}/{}".format(host, cleaned)


def _run_git(path: Path, *arguments: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    output = completed.stdout.strip()
    return output or None


def _stable_hash(value: Any, length: int = SHORT_ID_LENGTH) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:length]


def _git_facts(path: Path) -> Optional[Dict[str, Any]]:
    root = _run_git(path, "rev-parse", "--show-toplevel")
    if root is None:
        return None
    normalized_root = normalize_project_path(Path(root))
    remote = _run_git(Path(root), "remote", "get-url", "origin")
    if remote is None:
        remotes = _run_git(Path(root), "remote")
        if remotes:
            first_remote = sorted(remotes.splitlines())[0]
            remote = _run_git(Path(root), "remote", "get-url", first_remote)
    history = _run_git(Path(root), "rev-list", "--max-parents=0", "--all")
    history_roots = tuple(sorted(history.splitlines())) if history else ()
    return {
        "path": normalized_root,
        "remote": normalize_git_remote(remote, Path(root)),
        "history_roots": history_roots,
    }


def project_fingerprint(path: Path) -> Dict[str, Any]:
    git_facts = _git_facts(Path(path))
    if git_facts is not None:
        return {
            "kind": "git",
            "path": git_facts["path"],
            "remote": git_facts["remote"],
            "history_roots": git_facts["history_roots"],
        }
    return {
        "kind": "directory",
        "path": normalize_project_path(Path(path)),
    }


def project_id(fingerprint: Dict[str, Any]) -> str:
    return _stable_hash(fingerprint)


def _relocation_candidates(fingerprint: Dict[str, Any]) -> Tuple[str, ...]:
    if fingerprint["kind"] != "git":
        return ()
    remote = fingerprint.get("remote")
    roots = tuple(fingerprint.get("history_roots", ()))
    candidates = []
    if remote and roots:
        candidates.append(_stable_hash({"remote": remote, "history_roots": roots}))
    if roots:
        candidates.append(_stable_hash({"history_roots": roots}))
    elif remote:
        candidates.append(_stable_hash({"remote": remote}))
    return tuple(dict.fromkeys(candidates))


def _safe_slug(value: str, fallback: str = "项目") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f\x7f]+", "-", value.strip())
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-. ")
    if not value or value in {".", ".."}:
        value = fallback
    reserved_names = {"CON", "PRN", "AUX", "NUL"}
    reserved_names.update("COM{}".format(number) for number in range(1, 10))
    reserved_names.update("LPT{}".format(number) for number in range(1, 10))
    if value.split(".", 1)[0].upper() in reserved_names:
        value = "_{}".format(value)
    return value[:64]


def identify_project(path: Path) -> ProjectIdentity:
    fingerprint = project_fingerprint(Path(path))
    identifier = project_id(fingerprint)
    normalized_path = fingerprint["path"]
    name = (
        ntpath.basename(normalized_path)
        if _looks_like_windows_path(normalized_path)
        else Path(normalized_path).name
    )
    return ProjectIdentity(
        project_id=identifier,
        directory_name="{}-{}".format(_safe_slug(name), identifier[:8]),
        normalized_path=normalized_path,
        is_git=fingerprint["kind"] == "git",
        normalized_remote=fingerprint.get("remote"),
        history_roots=tuple(fingerprint.get("history_roots", ())),
        relocation_candidates=_relocation_candidates(fingerprint),
    )


def workflow_id(project_identifier: str, workflow_key: str) -> str:
    return _stable_hash(
        {"project_id": project_identifier, "workflow_key": workflow_key}
    )


def new_workflow_id() -> str:
    return uuid.uuid4().hex[:SHORT_ID_LENGTH]


def workflow_directory_name(
    workflow_name: str,
    project_identifier: str,
    workflow_key: str,
    created_on: date,
) -> str:
    identifier = workflow_id(project_identifier, workflow_key)
    workflow_date = created_on
    if isinstance(workflow_date, date):
        date_segment = workflow_date.isoformat()
    else:
        date_segment = str(workflow_date)
    return "{}-{}-{}".format(
        _safe_slug(date_segment, "日期"),
        _safe_slug(workflow_name, "工作流"),
        identifier[:8],
    )


__all__ = [
    "HUMAN_GATES",
    "InvalidTransition",
    "LEGAL_TRANSITIONS",
    "LEDGER_RECORD_TYPES",
    "LedgerContractError",
    "PHASE_GATE_REQUIREMENTS",
    "ProjectIdentity",
    "SHORT_ID_LENGTH",
    "STATES",
    "StateContractError",
    "WORKFLOW_STATES",
    "can_transition",
    "create_ledger_record",
    "format_record_id",
    "identify_project",
    "new_workflow_id",
    "normalize_git_remote",
    "normalize_project_path",
    "project_fingerprint",
    "project_id",
    "revise_ledger_record",
    "revise_record",
    "transition_state",
    "validate_human_gate",
    "validate_gate_contract",
    "validate_ledger",
    "validate_ledger_history",
    "validate_phase",
    "validate_phase_entry",
    "validate_transition",
    "workflow_directory_name",
    "workflow_id",
]
