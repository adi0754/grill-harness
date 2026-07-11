"""Shared storage primitives for Grill Harness."""

import errno
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


TEST_STORAGE_ROOT_ENV = "GRILL_HARNESS_TEST_ROOT"
TEST_ROOT_ENV = TEST_STORAGE_ROOT_ENV
_WINDOWS = os.name == "nt"

STORAGE_DIRECTORIES = {
    "config": "配置",
    "upstream": "上游管理",
    "projects": "项目",
    "templates": "模板",
    "logs": "日志",
}


def resolve_storage_root(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Return the user storage root without creating it.

    The environment override is deliberately named as a test root so normal
    production configuration cannot silently redirect durable user data.
    """

    source = os.environ if environ is None else environ
    override = source.get(TEST_STORAGE_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".grill-harness").resolve()


get_storage_root = resolve_storage_root


def ensure_storage_layout(root: Optional[Path] = None) -> Dict[str, Path]:
    """Create and return the required user-level Chinese directories."""

    storage_root = resolve_storage_root() if root is None else Path(root).expanduser().resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    paths = {
        key: storage_root / directory_name
        for key, directory_name in STORAGE_DIRECTORIES.items()
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


initialize_storage = ensure_storage_layout


def ensure_project_layout(project_directory: Path) -> Dict[str, Path]:
    """Create storage that belongs to one identified project."""

    project_root = Path(project_directory).expanduser().resolve()
    workflows = project_root / "工作流"
    workflows.mkdir(parents=True, exist_ok=True)
    return {"workflows": workflows}


def _reject_non_finite_json(value: str) -> None:
    raise ValueError("non-finite JSON number is not supported: {}".format(value))


def read_yaml(path: Path, default: Any = None) -> Any:
    """Read JSON-compatible YAML.

    JSON is intentionally used as the on-disk representation because it is a
    dependency-free subset of YAML with unambiguous round trips.
    """

    source = Path(path)
    if not source.exists():
        return default
    with source.open("r", encoding="utf-8") as stream:
        return json.load(stream, parse_constant=_reject_non_finite_json)


load_yaml = read_yaml


_UNSUPPORTED_FSYNC_ERRNOS = {
    errno.EINVAL,
    getattr(errno, "ENOTSUP", errno.EINVAL),
    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    getattr(errno, "ENOSYS", errno.EINVAL),
}


def _fsync(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in _UNSUPPORTED_FSYNC_ERRNOS:
            raise


def _directory_fsync_is_unsupported(error: OSError) -> bool:
    if error.errno in _UNSUPPORTED_FSYNC_ERRNOS:
        return True
    return _WINDOWS and error.errno in {errno.EACCES, errno.EPERM}


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = None
    try:
        descriptor = os.open(str(directory), flags)
        _fsync(descriptor)
    except OSError as error:
        if not _directory_fsync_is_unsupported(error):
            raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def atomic_write_yaml(path: Path, data: Any) -> None:
    """Atomically write JSON-compatible YAML beside the destination file."""

    serialized = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
        allow_nan=False,
    ) + "\n"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix=".{}.".format(destination.name),
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(serialized)
            stream.flush()
            _fsync(stream.fileno())
        os.replace(str(temporary_path), str(destination))
        temporary_path = None
        _fsync_directory(destination.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


write_yaml_atomic = atomic_write_yaml


def backup_before_schema_migration(
    path: Path,
    backup_directory: Optional[Path] = None,
) -> Optional[Path]:
    """Create a byte-for-byte backup before a destructive schema migration."""

    source = Path(path)
    if not source.exists():
        return None
    destination_directory = (
        source.parent / "备份"
        if backup_directory is None
        else Path(backup_directory)
    )
    destination_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = destination_directory / (
        "{}.{}.{}.bak".format(source.name, timestamp, uuid.uuid4().hex[:8])
    )
    shutil.copy2(str(source), str(backup))
    with backup.open("rb") as stream:
        _fsync(stream.fileno())
    _fsync_directory(destination_directory)
    return backup


backup_file = backup_before_schema_migration


__all__ = [
    "STORAGE_DIRECTORIES",
    "TEST_ROOT_ENV",
    "TEST_STORAGE_ROOT_ENV",
    "atomic_write_yaml",
    "backup_before_schema_migration",
    "backup_file",
    "ensure_storage_layout",
    "ensure_project_layout",
    "get_storage_root",
    "initialize_storage",
    "load_yaml",
    "read_yaml",
    "resolve_storage_root",
    "write_yaml_atomic",
]
