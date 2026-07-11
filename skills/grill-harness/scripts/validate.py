"""Pure validation and reconciliation for Grill Harness workflow artifacts."""

import copy
import os
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


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _id_list(value: Any) -> bool:
    return isinstance(value, list) and all(_nonempty_string(item) for item in value)


def validate_evidence(
    evidence: Mapping[str, Any], current_baseline: str = None
) -> Dict[str, Any]:
    """Validate whether one evidence record can support a completion claim."""

    conflicts = []
    evidence_id = evidence.get("id", "<unknown>")
    if not _nonempty_string(evidence.get("id")):
        conflicts.append(
            _conflict(
                "EVIDENCE_ID",
                "证据记录缺少稳定的非空 ID，无法建立追踪关系。",
                "分配唯一 EVD ID，并重新关联需求、决策和任务。",
                evidence_id=evidence_id,
            )
        )
    if not _nonempty_string(evidence.get("command")):
        conflicts.append(
            _conflict(
                "EVIDENCE_COMMAND",
                "证据 {} 缺少实际执行的非空命令。".format(evidence_id),
                "在目标环境重新运行验证，并记录未经改写的实际命令。",
                evidence_id=evidence_id,
            )
        )
    working_directory = evidence.get("working_directory")
    if not _nonempty_string(working_directory) or not os.path.isabs(working_directory):
        conflicts.append(
            _conflict(
                "EVIDENCE_WORKING_DIRECTORY",
                "证据 {} 缺少实际工作目录。".format(evidence_id),
                "记录验证命令执行时的真实绝对工作目录后重新验收。",
                evidence_id=evidence_id,
            )
        )
    exit_code = evidence.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code != 0:
        conflicts.append(
            _conflict(
                "EVIDENCE_EXIT_CODE",
                "证据 {} 的退出码不是整数 0，不能证明验证通过。".format(evidence_id),
                "修复失败并重新执行命令；保留原失败证据但不要用于通过结论。",
                evidence_id=evidence_id,
                exit_code=exit_code,
            )
        )
    baseline = evidence.get("baseline")
    if (
        not _nonempty_string(baseline)
        or not _nonempty_string(current_baseline)
        or baseline != current_baseline
    ):
        conflicts.append(
            _conflict(
                "EVIDENCE_BASELINE",
                "证据 {} 的 Git 基线缺失或与当前仓库不一致。".format(evidence_id),
                "在当前基线重新运行验证并登记新的证据记录。",
                evidence_id=evidence_id,
                evidence_baseline=baseline,
                current_baseline=current_baseline,
            )
        )
    if not _nonempty_string(evidence.get("producer")):
        conflicts.append(
            _conflict(
                "EVIDENCE_PRODUCER",
                "证据 {} 未记录真实产生者。".format(evidence_id),
                "记录执行验证的角色或 Agent 身份，并重新确认来源。",
                evidence_id=evidence_id,
            )
        )
    if evidence.get("reproducible") is not True:
        conflicts.append(
            _conflict(
                "EVIDENCE_REPRODUCIBILITY",
                "证据 {} 未证明可以复现。".format(evidence_id),
                "补齐可重复执行的命令、环境和输入后重新验证。",
                evidence_id=evidence_id,
            )
        )
    trace_fields = ("requirements", "decisions", "tasks", "issues")
    trace_values = [evidence.get(field) for field in trace_fields]
    if (
        any(not _id_list(value) for value in trace_values)
        or not any(value for value in trace_values if isinstance(value, list))
    ):
        conflicts.append(
            _conflict(
                "EVIDENCE_TRACEABILITY",
                "证据 {} 缺少有效的需求、决策、任务或问题关联。".format(evidence_id),
                "使用字符串 ID 列表记录关联对象，并至少关联一项后重新验收。",
                evidence_id=evidence_id,
            )
        )
    if not _nonempty_string(evidence.get("executed_at")):
        conflicts.append(
            _conflict(
                "EVIDENCE_EXECUTED_AT",
                "证据 {} 缺少实际执行时间。".format(evidence_id),
                "记录带时区的真实执行时间，并在证据过期时重新运行。",
                evidence_id=evidence_id,
            )
        )
    output_path = evidence.get("output_path")
    if not _nonempty_string(output_path) or not os.path.isabs(output_path):
        conflicts.append(
            _conflict(
                "EVIDENCE_OUTPUT_PATH",
                "证据 {} 缺少原始输出的绝对路径。".format(evidence_id),
                "保存原始输出并记录可定位的绝对路径，不要只复制摘要。",
                evidence_id=evidence_id,
            )
        )
    if (
        evidence.get("status") != "valid"
        or evidence.get("currentness") != "current"
        or bool(evidence.get("stale_because"))
    ):
        conflicts.append(
            _conflict(
                "STALE_EVIDENCE",
                "证据 {} 已过期或当前状态无效。".format(evidence_id),
                "按当前代码、规格和 Git 基线重新执行验证并登记新证据。",
                evidence_id=evidence_id,
                status=evidence.get("status"),
                currentness=evidence.get("currentness"),
            )
        )
    return {"valid": not conflicts, "conflicts": conflicts}


def validate_evidence_records(
    records: Iterable[Mapping[str, Any]], current_baseline: str = None
) -> Dict[str, Any]:
    """Validate a collection without hiding which evidence record failed."""

    reports = []
    conflicts = []
    for evidence in records:
        report = validate_evidence(evidence, current_baseline=current_baseline)
        reports.append({"evidence_id": evidence.get("id"), **report})
        conflicts.extend(report["conflicts"])
    return {"valid": not conflicts, "reports": reports, "conflicts": conflicts}


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
    "validate_evidence",
    "validate_evidence_records",
]
