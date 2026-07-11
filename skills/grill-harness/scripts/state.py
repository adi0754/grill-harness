"""Project and workflow identity for Grill Harness storage."""

import hashlib
import json
import ntpath
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlsplit


SHORT_ID_LENGTH = 12


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
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("\\\\")


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
    if _looks_like_windows_path(value):
        normalized_path = normalize_project_path(value)
        if normalized_path.startswith("\\\\"):
            return "file://{}".format(
                normalized_path.lstrip("\\").replace("\\", "/")
            )
        return "file://{}".format(normalized_path)
    scp_match = re.match(r"^(?:[^@/]+@)?([^:/]+):(.+)$", value)
    if scp_match and "://" not in value:
        host = scp_match.group(1).lower()
        repository_path = scp_match.group(2)
        return _clean_remote_path(host, repository_path)

    parsed = urlsplit(value)
    if parsed.scheme and parsed.scheme != "file":
        host = (parsed.hostname or "").lower()
        return _clean_remote_path(host, unquote(parsed.path))
    if parsed.scheme == "file":
        file_path = unquote(parsed.path)
        if parsed.netloc:
            server = (parsed.hostname or parsed.netloc).lower()
            if server == "localhost":
                if re.match(r"^/[A-Za-z]:[\\/]", file_path):
                    file_path = file_path[1:]
                return "file://{}".format(normalize_project_path(file_path))
            return "file://{}/{}".format(server, file_path.strip("/").lower())
        if re.match(r"^/[A-Za-z]:[\\/]", file_path):
            file_path = file_path[1:]
        return "file://{}".format(normalize_project_path(file_path))

    local_path = Path(value).expanduser()
    if not local_path.is_absolute() and repository_root is not None:
        local_path = Path(repository_root) / local_path
    return "file://{}".format(normalize_project_path(local_path))


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
    created_on: Optional[date] = None,
) -> str:
    identifier = workflow_id(project_identifier, workflow_key)
    workflow_date = date.today() if created_on is None else created_on
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
    "ProjectIdentity",
    "SHORT_ID_LENGTH",
    "identify_project",
    "new_workflow_id",
    "normalize_git_remote",
    "normalize_project_path",
    "project_fingerprint",
    "project_id",
    "workflow_directory_name",
    "workflow_id",
]
