"""Pure validation and reconciliation for Grill Harness workflow artifacts."""

import copy
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Set

import state


class ArtifactContractError(ValueError):
    """Raised before mutation when artifact identity is contradictory."""


def _conflict(
    code: str,
    conflict: str,
    recovery_action: str,
    **details: Any
) -> Dict[str, Any]:
    item = {
        "code": code,
        "conflict": conflict,
        "recovery_action": recovery_action,
    }
    item.update(details)
    return item


def _records_by_id(records: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    indexed = {}
    for record in records:
        record_id = record.get("id")
        if isinstance(record_id, str):
            indexed[record_id] = record
    return indexed


def _identity_conflicts_for_records(
    collection_name: str,
    records: Iterable[Mapping[str, Any]],
    seen: MutableMapping[str, str],
) -> list:
    conflicts = []
    reported = set()
    for position, record in enumerate(records):
        if not isinstance(record, Mapping):
            conflicts.append(
                _conflict(
                    "INVALID_ID",
                    "{} 第 {} 条记录不是可识别的映射，无法确认其 ID。".format(
                        collection_name, position + 1
                    ),
                    "暂停传播，恢复原始记录结构并补齐唯一的非空字符串 ID。",
                    collection=collection_name,
                    position=position,
                )
            )
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            conflicts.append(
                _conflict(
                    "INVALID_ID",
                    "{} 第 {} 条记录缺少唯一的非空字符串 ID。".format(
                        collection_name, position + 1
                    ),
                    "暂停传播，确认记录来源并补齐稳定 ID 后重新对账。",
                    collection=collection_name,
                    position=position,
                )
            )
            continue
        if record_id not in seen:
            seen[record_id] = collection_name
            continue
        if record_id not in reported:
            conflicts.append(
                _conflict(
                    "DUPLICATE_ID",
                    "{} 中存在重复 ID {}，与 {} 的记录相互矛盾，后写记录不能覆盖前一条事实。".format(
                        collection_name, record_id, seen[record_id]
                    ),
                    "暂停对账，保留两条原始记录并由用户确认正确版本和替代关系。",
                    collection=collection_name,
                    record_id=record_id,
                )
            )
            reported.add(record_id)
    return conflicts


def identity_invariant_conflicts(workflow: Mapping[str, Any]) -> list:
    """Return the identity contradictions shared by read and mutation paths."""

    conflicts = _identity_conflicts_for_records(
        "phases", workflow.get("phases", ()), {}
    )
    shared_ids = {}
    for collection_name in ("artifacts", "tasks", "evidence"):
        conflicts.extend(
            _identity_conflicts_for_records(
                collection_name,
                workflow.get(collection_name, ()),
                shared_ids,
            )
        )
    return conflicts


def _require_identity_invariants(workflow: Mapping[str, Any]) -> None:
    conflicts = identity_invariant_conflicts(workflow)
    if conflicts:
        first = conflicts[0]
        raise ArtifactContractError(
            "{} 恢复动作：{}".format(
                first["conflict"], first["recovery_action"]
            )
        )


def reconcile_workflow(workflow: Mapping[str, Any]) -> Dict[str, Any]:
    """Report state/artifact contradictions without changing the workflow."""

    conflicts = identity_invariant_conflicts(workflow)
    if conflicts:
        return {"valid": False, "conflicts": conflicts}
    artifacts = _records_by_id(workflow.get("artifacts", ()))
    evidence = _records_by_id(workflow.get("evidence", ()))
    for phase in workflow.get("phases", ()):
        phase_id = phase.get("id", "<unknown>")
        try:
            state.validate_phase(phase)
        except (ValueError, state.StateContractError) as error:
            conflicts.append(
                _conflict(
                    "PHASE_CONTRACT",
                    "阶段 {} 的状态与产物契约冲突：{}".format(phase_id, error),
                    "暂停该阶段，补齐真实产物和证据后再重新完成。",
                    phase_id=phase_id,
                )
            )
        if phase.get("status") != "completed":
            continue
        for artifact_id in phase.get("artifacts", ()):
            artifact = artifacts.get(artifact_id)
            if artifact is None:
                conflicts.append(
                    _conflict(
                        "MISSING_ARTIFACT",
                        "阶段 {} 声称已完成，但产物 {} 不存在。".format(
                            phase_id, artifact_id
                        ),
                        "从真实仓库确认产物，补建索引或将阶段退回进行中。",
                        phase_id=phase_id,
                        artifact_id=artifact_id,
                    )
                )
            elif artifact.get("status") != "completed":
                conflicts.append(
                    _conflict(
                        "NONCURRENT_ARTIFACT",
                        "阶段 {} 引用的产物 {} 当前状态为 {}。".format(
                            phase_id, artifact_id, artifact.get("status")
                        ),
                        "处理产物失效原因并重新生成、复核后再完成阶段。",
                        phase_id=phase_id,
                        artifact_id=artifact_id,
                    )
                )
        for evidence_id in phase.get("evidence", ()):
            evidence_record = evidence.get(evidence_id)
            if evidence_record is None:
                conflicts.append(
                    _conflict(
                        "MISSING_EVIDENCE",
                        "阶段 {} 引用的证据 {} 不存在。".format(
                            phase_id, evidence_id
                        ),
                        "重新运行可复现验证并登记证据，然后再次验收该阶段。",
                        phase_id=phase_id,
                        evidence_id=evidence_id,
                    )
                )
            elif evidence_record.get("status") != "valid":
                conflicts.append(
                    _conflict(
                        "STALE_EVIDENCE",
                        "阶段 {} 引用的证据 {} 当前无效。".format(phase_id, evidence_id),
                        "按当前代码和规格重新执行验证并登记新证据。",
                        phase_id=phase_id,
                        evidence_id=evidence_id,
                    )
                )
    return {"valid": not conflicts, "conflicts": conflicts}


def _mark_stale(record: MutableMapping[str, Any], reason: str) -> None:
    record["currentness"] = "stale"
    record["stale_because"] = reason
    if record.get("status") not in ("superseded", "cancelled", "failed"):
        record["status"] = "stale"


def propagate_decision_change(
    workflow: Mapping[str, Any], decision_id: str
) -> Dict[str, Any]:
    """Copy a workflow and stale every explicitly decision-dependent output."""

    _require_identity_invariants(workflow)
    updated = copy.deepcopy(dict(workflow))
    affected: Set[str] = set()
    for collection_name in ("artifacts", "tasks", "evidence"):
        for record in updated.get(collection_name, ()):  # type: ignore[union-attr]
            if decision_id in record.get("decisions", ()):
                _mark_stale(record, decision_id)
                if isinstance(record.get("id"), str):
                    affected.add(record["id"])
    changed = True
    while changed:
        changed = False
        for collection_name in ("artifacts", "tasks", "evidence"):
            for record in updated.get(collection_name, ()):  # type: ignore[union-attr]
                record_id = record.get("id")
                if record_id in affected:
                    continue
                if affected.intersection(record.get("depends_on", ())):
                    _mark_stale(record, decision_id)
                    if isinstance(record_id, str):
                        affected.add(record_id)
                        changed = True
    return updated


def propagate_superseded(workflow: Mapping[str, Any], artifact_id: str) -> Dict[str, Any]:
    """Supersede an artifact and stale the transitive closure of its dependents."""

    _require_identity_invariants(workflow)
    updated = copy.deepcopy(dict(workflow))
    artifacts = _records_by_id(updated.get("artifacts", ()))
    target = artifacts.get(artifact_id)
    if target is None:
        raise ValueError("unknown artifact: {}".format(artifact_id))
    target["status"] = "superseded"
    affected: Set[str] = {artifact_id}
    changed = True
    while changed:
        changed = False
        for collection_name in ("artifacts", "tasks", "evidence"):
            for record in updated.get(collection_name, ()):  # type: ignore[union-attr]
                record_id = record.get("id")
                if record_id in affected:
                    continue
                if affected.intersection(record.get("depends_on", ())):
                    _mark_stale(record, artifact_id)
                    if isinstance(record_id, str) and record_id not in affected:
                        affected.add(record_id)
                        changed = True
    return updated


validate_artifacts = reconcile_workflow
reconcile_artifacts = reconcile_workflow
reconcile = reconcile_workflow
mark_decision_dependents_stale = propagate_decision_change


__all__ = [
    "ArtifactContractError",
    "identity_invariant_conflicts",
    "mark_decision_dependents_stale",
    "propagate_decision_change",
    "propagate_superseded",
    "reconcile",
    "reconcile_artifacts",
    "reconcile_workflow",
    "validate_artifacts",
]
