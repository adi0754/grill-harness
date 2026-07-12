"""Evidence-backed knowledge validation, query, draft, and promotion."""

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import common
import workflow_ops


KNOWLEDGE_TRUST_STATUSES = frozenset(
    ("tentative", "verified", "invalidated", "replaced")
)
KNOWLEDGE_SCHEMA_VERSION = 1


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _knowledge_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"KNW-[0-9]{3,}", value))


def _project_id(value):
    return isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
    )


def _string_list(value, *, allow_empty=False):
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray, Mapping))
        and (allow_empty or bool(value))
        and all(_non_empty_string(item) for item in value)
    )


def _conflict(field, message):
    return {"field": field, "conflict": message}


def _report(conflicts):
    return {"valid": not conflicts, "conflicts": conflicts}


def _timezone_aware_timestamp(value):
    if not _non_empty_string(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_knowledge_record(record):
    """Validate one KNW record without mutating it."""

    if not isinstance(record, Mapping):
        return _report([_conflict("record", "knowledge record must be a mapping")])
    conflicts = []
    if not _knowledge_id(record.get("id")):
        conflicts.append(_conflict("id", "knowledge record requires a stable KNW-xxx id"))
    for field in ("conclusion", "type", "source_workflow", "invalidation_condition"):
        if not _non_empty_string(record.get(field)):
            conflicts.append(_conflict(field, "{} must be non-empty".format(field)))
    for field in ("applicability", "evidence"):
        if not _string_list(record.get(field)):
            conflicts.append(_conflict(field, "{} must be a non-empty string list".format(field)))
    if not _string_list(record.get("non_applicability"), allow_empty=True):
        conflicts.append(
            _conflict("non_applicability", "non_applicability must be a string list")
        )
    trust_status = record.get("trust_status")
    if trust_status not in KNOWLEDGE_TRUST_STATUSES:
        conflicts.append(_conflict("trust_status", "unknown knowledge trust status"))
    if not _timezone_aware_timestamp(record.get("formed_at")):
        conflicts.append(_conflict("formed_at", "formed_at must be a timezone-aware ISO timestamp"))
    replaced_by = record.get("replaced_by")
    if replaced_by is not None and not _knowledge_id(replaced_by):
        conflicts.append(_conflict("replaced_by", "replaced_by must be null or a KNW-xxx id"))
    elif replaced_by == record.get("id"):
        conflicts.append(_conflict("replaced_by", "knowledge cannot replace itself"))
    if trust_status == "replaced" and replaced_by is None:
        conflicts.append(_conflict("replaced_by", "replaced knowledge requires replaced_by"))
    if trust_status != "replaced" and replaced_by is not None:
        conflicts.append(
            _conflict("replaced_by", "only replaced knowledge may declare replaced_by")
        )
    if record.get("type") == "route_failure":
        if record.get("failure_class") != "route_failure":
            conflicts.append(
                _conflict("failure_class", "route failure facts require confirmed route_failure class")
            )
    return _report(conflicts)


def _storage_root(storage_root=None):
    return (
        common.resolve_storage_root()
        if storage_root is None
        else Path(storage_root).expanduser().resolve()
    )


def _knowledge_paths(storage_root, project_id):
    if not _project_id(project_id):
        raise ValueError("project_id must be a safe stable identifier")
    knowledge_root = _storage_root(storage_root) / common.STORAGE_DIRECTORIES["knowledge"]
    return (
        knowledge_root / "项目知识" / str(project_id) / "knowledge.yaml",
        knowledge_root / "通用知识" / "knowledge.yaml",
    )


def _load_records(path):
    payload = common.read_yaml(path, default={"schema_version": 1, "records": []})
    return _records_from_payload(payload, path)


def _records_from_payload(payload, path):
    if not isinstance(payload, Mapping) or payload.get("schema_version") != KNOWLEDGE_SCHEMA_VERSION:
        raise ValueError("knowledge store must use schema_version 1: {}".format(path))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("knowledge store records must be a list: {}".format(path))
    for record in records:
        report = validate_knowledge_record(record)
        if not report["valid"]:
            raise ValueError(report["conflicts"][0]["conflict"])
    return copy.deepcopy(records)


def _store_snapshot(path):
    lock_path = path.parent / ".knowledge.lock"
    with common.exclusive_directory_lock(lock_path):
        if path.is_file():
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        else:
            raw = b"<missing>"
            payload = {"schema_version": KNOWLEDGE_SCHEMA_VERSION, "records": []}
        return _records_from_payload(payload, path), hashlib.sha256(raw).hexdigest()


def _matches(record, terms):
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).casefold()
    return all(term.casefold() in haystack for term in terms)


def query_knowledge(project_id, query=None, *, storage_root=None, include_general=True):
    """Read matching project/general knowledge without creating or changing files."""

    if not _project_id(project_id):
        raise ValueError("project_id must be a safe stable identifier")
    if query is None:
        terms = []
    elif isinstance(query, str):
        terms = [query.strip()] if query.strip() else []
    elif _string_list(query, allow_empty=True):
        terms = [item.strip() for item in query]
    else:
        raise ValueError("query must be a string or string list")
    project_path, general_path = _knowledge_paths(storage_root, project_id)
    sources = [("project", project_path)]
    if include_general:
        sources.append(("general", general_path))
    results = []
    for scope, path in sources:
        if not path.is_file():
            continue
        for stored in _load_records(path):
            if not _matches(stored, terms):
                continue
            record = copy.deepcopy(stored)
            record["scope"] = scope
            record["can_guide_planning"] = record.get("trust_status") == "verified"
            results.append(record)
    results.sort(key=lambda item: (item["scope"] != "project", item["id"]))
    return {
        "read_only": True,
        "project_id": project_id,
        "query": terms,
        "records": results,
        "guidance": [item for item in results if item["can_guide_planning"]],
        "historical": [item for item in results if not item["can_guide_planning"]],
        "searched_paths": [str(path) for _, path in sources],
    }


def _workflow_state_path(workflow_value):
    path = Path(workflow_value).expanduser().resolve()
    if path.is_dir():
        nested = path / "系统" / "state.yaml"
        path = nested if nested.is_file() else path / "state.yaml"
    try:
        path.relative_to(common.resolve_storage_root())
    except ValueError:
        raise ValueError("knowledge mutation is only allowed under ~/.grill-harness")
    if not path.is_file():
        raise ValueError("workflow state does not exist: {}".format(path))
    return path


def _workflow(workflow_value):
    state_path = _workflow_state_path(workflow_value)
    payload = common.read_yaml(state_path)
    if not isinstance(payload, Mapping):
        raise ValueError("workflow state must be a mapping")
    return state_path, payload


def write_learning_draft(workflow_value, record):
    """Persist a tentative machine-readable draft inside the current workflow."""

    state_path, workflow = _workflow(workflow_value)
    candidate = copy.deepcopy(dict(record)) if isinstance(record, Mapping) else record
    if not isinstance(candidate, dict):
        raise ValueError("knowledge draft must be a mapping")
    candidate["trust_status"] = "tentative"
    candidate["replaced_by"] = None
    if not _non_empty_string(candidate.get("source_workflow")):
        candidate["source_workflow"] = workflow.get("workflow_id")
    if candidate.get("source_workflow") != workflow.get("workflow_id"):
        raise ValueError("knowledge draft source_workflow must match the current workflow")
    report = validate_knowledge_record(candidate)
    if not report["valid"]:
        raise ValueError(report["conflicts"][0]["conflict"])
    draft_directory = state_path.parent.parent / "过程产物" / "学习草稿"
    destination = draft_directory / "{}.yaml".format(candidate["id"])
    common.atomic_write_yaml(destination, candidate)
    return {"path": str(destination), "record": candidate, "tentative": True}


def _record_fingerprint(record):
    return (
        record.get("conclusion"),
        record.get("type"),
        tuple(record.get("applicability", ())),
        tuple(record.get("non_applicability", ())),
    )


def _replacement_ids(record):
    value = record.get("replaces", record.get("replacement_for", []))
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not _string_list(value, allow_empty=True) or any(not _knowledge_id(item) for item in value):
        raise ValueError("replaces must contain KNW-xxx ids")
    return list(value)


def preview_promotion(existing_records, candidate_records, *, scope="project"):
    """Compute additions, deduplication, and explicit replacement links purely."""

    if scope not in {"project", "general"}:
        raise ValueError("knowledge scope must be project or general")
    if not isinstance(existing_records, list) or not isinstance(candidate_records, list):
        raise ValueError("knowledge preview inputs must be lists")
    merged = copy.deepcopy(existing_records)
    by_id = {}
    by_fingerprint = {}
    for record in merged:
        report = validate_knowledge_record(record)
        if not report["valid"]:
            raise ValueError(report["conflicts"][0]["conflict"])
        if record["id"] in by_id:
            raise ValueError("duplicate knowledge id in store: {}".format(record["id"]))
        by_id[record["id"]] = record
        by_fingerprint[_record_fingerprint(record)] = record
    additions = []
    duplicates = []
    replacements = []
    conflicts = []
    for raw_candidate in candidate_records:
        if not isinstance(raw_candidate, Mapping):
            raise ValueError("knowledge candidate must be a mapping")
        candidate = copy.deepcopy(dict(raw_candidate))
        candidate["trust_status"] = "verified"
        candidate["replaced_by"] = None
        replacement_ids = _replacement_ids(candidate)
        candidate.pop("replaces", None)
        candidate.pop("replacement_for", None)
        report = validate_knowledge_record(candidate)
        if not report["valid"]:
            raise ValueError(report["conflicts"][0]["conflict"])
        same_id = by_id.get(candidate["id"])
        if same_id is not None:
            if _record_fingerprint(same_id) == _record_fingerprint(candidate):
                duplicates.append(candidate["id"])
                continue
            conflicts.append({
                "candidate_id": candidate["id"],
                "existing_id": candidate["id"],
                "conflict": "stable knowledge id cannot be overwritten",
            })
            continue
        same_fact = by_fingerprint.get(_record_fingerprint(candidate))
        if same_fact is not None and not replacement_ids:
            duplicates.append(same_fact["id"])
            continue
        applicability = set(candidate.get("applicability", ()))
        unlinked_conflicts = [
            item
            for item in merged
            if item.get("trust_status") == "verified"
            and item.get("type") == candidate.get("type")
            and item.get("conclusion") != candidate.get("conclusion")
            and applicability.intersection(item.get("applicability", ()))
            and item.get("id") not in replacement_ids
        ]
        if unlinked_conflicts:
            conflicts.append({
                "candidate_id": candidate["id"],
                "existing_id": unlinked_conflicts[0]["id"],
                "conflict": "conflicting current knowledge requires an explicit replaced_by link",
            })
            continue
        replacement_targets = []
        for old_id in replacement_ids:
            old = by_id.get(old_id)
            if old is None or old_id == candidate["id"]:
                conflicts.append({
                    "candidate_id": candidate["id"],
                    "existing_id": old_id,
                    "conflict": "replacement target must be an existing different KNW record",
                })
                replacement_targets = None
                break
            if old.get("trust_status") == "replaced" and old.get("replaced_by") != candidate["id"]:
                conflicts.append({
                    "candidate_id": candidate["id"],
                    "existing_id": old_id,
                    "conflict": "replacement target already has a different replaced_by link",
                })
                replacement_targets = None
                break
            replacement_targets.append(old)
        if replacement_targets is None:
            continue
        for old in replacement_targets:
            old["trust_status"] = "replaced"
            old["replaced_by"] = candidate["id"]
            replacements.append({"old_id": old["id"], "replaced_by": candidate["id"]})
        merged.append(candidate)
        by_id[candidate["id"]] = candidate
        by_fingerprint[_record_fingerprint(candidate)] = candidate
        additions.append(candidate["id"])
    return {
        "scope": scope,
        "ready": not conflicts,
        "additions": additions,
        "duplicates": duplicates,
        "replacements": replacements,
        "conflicts": conflicts,
        "records": merged,
    }


def _require_project_ownership(workflow, project_id):
    if workflow.get("project_id") != project_id:
        raise ValueError("project does not own the selected workflow")


def _knowledge_file(project_id, scope, storage_root=None):
    project_path, general_path = _knowledge_paths(storage_root, project_id)
    return project_path if scope == "project" else general_path


def _store_hash(path):
    return hashlib.sha256(path.read_bytes() if path.is_file() else b"<missing>").hexdigest()


def _preview_id(payload):
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "KPV-{}".format(hashlib.sha256(canonical).hexdigest()[:16])


def _route_failure_records(records):
    if not records:
        raise ValueError("route failure promotion requires at least one record")
    for record in records:
        if not isinstance(record, Mapping) or record.get("type") != "route_failure":
            raise ValueError("route failure exception only accepts project route_failure facts")
        if record.get("failure_class") != "route_failure" or not _string_list(record.get("evidence")):
            raise ValueError("route failure fact requires objective evidence and confirmed class")


def _general_candidates(project_id, records, storage_root=None):
    project_path = _knowledge_file(project_id, "project", storage_root)
    project_records, source_hash = _store_snapshot(project_path)
    verified = {
        item["id"]: item
        for item in project_records
        if item.get("trust_status") == "verified"
    }
    selected = []
    for record in records:
        if not isinstance(record, Mapping) or record.get("type") == "route_failure":
            raise ValueError("route failure facts cannot become general knowledge")
        source = verified.get(record.get("id"))
        if source is None or _record_fingerprint(source) != _record_fingerprint(record):
            raise ValueError(
                "general promotion requires an existing verified project knowledge record"
            )
        selected.append(copy.deepcopy(source))
    return selected, project_path, source_hash


def _create_promotion_preview(
    workflow_value,
    project_id,
    records,
    *,
    scope,
    storage_root=None,
    route_failure=False,
):
    if not isinstance(records, list) or not records:
        raise ValueError("knowledge promotion requires at least one record")
    state_path, workflow = _workflow(workflow_value)
    _require_project_ownership(workflow, project_id)
    if route_failure:
        if scope != "project":
            raise ValueError("route failure facts cannot become general knowledge")
        _route_failure_records(records)
    elif any(
        isinstance(item, Mapping) and item.get("type") == "route_failure"
        for item in records
    ):
        if scope == "general":
            raise ValueError("route failure facts cannot become general knowledge")
        raise ValueError("route failure facts require the bounded project exception")
    source_path = None
    source_hash = None
    if scope == "general":
        candidates, source_path, source_hash = _general_candidates(
            project_id, records, storage_root
        )
    else:
        candidates = records
    knowledge_path = _knowledge_file(project_id, scope, storage_root)
    existing_records, base_store_hash = _store_snapshot(knowledge_path)
    preview = preview_promotion(existing_records, candidates, scope=scope)
    if not preview["ready"]:
        raise ValueError(preview["conflicts"][0]["conflict"])
    core = {
        "schema_version": 1,
        "project_id": project_id,
        "workflow_id": workflow.get("workflow_id"),
        "scope": scope,
        "route_failure": bool(route_failure),
        "base_store_hash": base_store_hash,
        "knowledge_path": str(knowledge_path),
        "preview": preview,
    }
    if source_path is not None:
        core.update({
            "source_project_path": str(source_path),
            "source_project_hash": source_hash,
            "source_record_ids": [item["id"] for item in candidates],
        })
    identifier = _preview_id(core)
    payload = dict(core, preview_id=identifier)
    preview_path = (
        state_path.parent.parent
        / "过程产物"
        / "学习草稿"
        / "知识变更预览-{}.yaml".format(identifier)
    )
    common.atomic_write_yaml(preview_path, payload)
    result = copy.deepcopy(preview)
    result.update({
        "preview_id": identifier,
        "path": str(preview_path),
        "knowledge_path": str(knowledge_path),
        "applied": False,
    })
    return result


def _load_promotion_preview(workflow_value, project_id, preview_value, scope):
    state_path, workflow = _workflow(workflow_value)
    _require_project_ownership(workflow, project_id)
    path = Path(preview_value).expanduser().resolve()
    try:
        path.relative_to((state_path.parent.parent / "过程产物" / "学习草稿").resolve())
    except ValueError:
        raise ValueError("knowledge preview must be inside the current workflow")
    payload = common.read_yaml(path)
    if not isinstance(payload, Mapping):
        raise ValueError("knowledge preview must be a mapping")
    core = {key: value for key, value in payload.items() if key != "preview_id"}
    if payload.get("preview_id") != _preview_id(core):
        raise ValueError("knowledge preview content hash does not match preview_id")
    if (
        payload.get("project_id") != project_id
        or payload.get("workflow_id") != workflow.get("workflow_id")
        or payload.get("scope") != scope
    ):
        raise ValueError("knowledge preview does not belong to this project/workflow/scope")
    knowledge_path = Path(payload.get("knowledge_path", "")).resolve()
    if payload.get("base_store_hash") != _store_hash(knowledge_path):
        raise ValueError("knowledge store changed after preview; create a new preview")
    preview = payload.get("preview")
    if not isinstance(preview, Mapping) or not preview.get("ready"):
        raise ValueError("knowledge preview is not ready to apply")
    return state_path, workflow, path, payload


def promote_project_knowledge(
    workflow_value,
    project_id,
    records=None,
    *,
    storage_root=None,
    preview=None,
    approval_id=None,
    route_failure=False,
    failure_approval_id=None,
):
    """Create a project preview, then apply only a preview-bound approval."""

    if preview is None:
        return _create_promotion_preview(
            workflow_value,
            project_id,
            records,
            scope="project",
            storage_root=storage_root,
            route_failure=route_failure,
        )
    state_path, _, _, payload = _load_promotion_preview(
        workflow_value, project_id, preview, "project"
    )
    if bool(payload.get("route_failure")) != bool(route_failure):
        raise ValueError("route failure mode must match the approved preview")
    preview_report = payload["preview"]
    promoted_ids = list(preview_report.get("additions", ())) or [
        item["id"] for item in preview_report.get("records", ())
        if isinstance(item, Mapping) and _knowledge_id(item.get("id"))
    ]
    knowledge_payload = {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "records": preview_report["records"],
    }
    if route_failure:
        if not _non_empty_string(failure_approval_id):
            raise ValueError("route failure requires a persisted classification approval")
        evidence_ids = sorted({
            evidence_id
            for item in preview_report["records"]
            if isinstance(item, Mapping) and item.get("type") == "route_failure"
            for evidence_id in item.get("evidence", ())
        })
        workflow_ops.commit_knowledge_update(
            state_path,
            payload["knowledge_path"],
            knowledge_payload,
            preview_id=payload["preview_id"],
            approval_requirements=[(failure_approval_id, "route_failure")],
            route_failure=True,
            evidence_ids=evidence_ids,
            expected_store_hash=payload["base_store_hash"],
        )
    else:
        if not _non_empty_string(approval_id):
            raise ValueError("knowledge archive requires a preview-bound user approval")
        workflow_ops.commit_knowledge_update(
            state_path,
            payload["knowledge_path"],
            knowledge_payload,
            preview_id=payload["preview_id"],
            approval_requirements=[(approval_id, "knowledge_archive")],
            artifact_ids=promoted_ids,
            complete_archive=True,
            expected_store_hash=payload["base_store_hash"],
        )
    return {
        "scope": "project",
        "path": payload["knowledge_path"],
        "preview": preview_report,
        "preview_id": payload["preview_id"],
        "route_failure_exception": bool(route_failure),
        "archive_completed": not route_failure,
        "applied": True,
    }


def promote_general_knowledge(
    workflow_value,
    project_id,
    records=None,
    *,
    storage_root=None,
    preview=None,
    approval_id=None,
    general_approval_id=None,
):
    """Create a general preview from verified project knowledge, then apply it."""

    if preview is None:
        return _create_promotion_preview(
            workflow_value,
            project_id,
            records,
            scope="general",
            storage_root=storage_root,
        )
    state_path, workflow, _, payload = _load_promotion_preview(
        workflow_value, project_id, preview, "general"
    )
    if (
        not _non_empty_string(approval_id)
        or not _non_empty_string(general_approval_id)
        or approval_id == general_approval_id
    ):
        raise ValueError("general knowledge requires a separate second user approval")
    archive_confirmation = workflow.get("archive_confirmation")
    if not (
        isinstance(archive_confirmation, Mapping)
        and archive_confirmation.get("status") == "approved"
        and archive_confirmation.get("approval_id") == approval_id
        and _non_empty_string(archive_confirmation.get("preview_id"))
    ):
        raise ValueError("general knowledge requires the completed project archive approval")
    preview_report = payload["preview"]
    workflow_ops.commit_knowledge_update(
        state_path,
        payload["knowledge_path"],
        {"schema_version": KNOWLEDGE_SCHEMA_VERSION, "records": preview_report["records"]},
        preview_id=payload["preview_id"],
        approval_requirements=[
            (
                approval_id,
                "knowledge_archive",
                archive_confirmation["preview_id"],
            ),
            (general_approval_id, "general_knowledge"),
        ],
        expected_store_hash=payload["base_store_hash"],
        source_project_path=payload.get("source_project_path"),
        expected_source_hash=payload.get("source_project_hash"),
    )
    return {
        "scope": "general",
        "path": payload["knowledge_path"],
        "preview": preview_report,
        "preview_id": payload["preview_id"],
        "route_failure_exception": False,
        "archive_completed": True,
        "separate_general_approval": True,
        "applied": True,
    }


__all__ = [
    "KNOWLEDGE_SCHEMA_VERSION",
    "KNOWLEDGE_TRUST_STATUSES",
    "preview_promotion",
    "promote_general_knowledge",
    "promote_project_knowledge",
    "query_knowledge",
    "validate_knowledge_record",
    "write_learning_draft",
]
