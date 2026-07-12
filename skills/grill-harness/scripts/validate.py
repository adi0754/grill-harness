"""Pure validation and reconciliation for Grill Harness workflow artifacts."""

import copy
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Set

import state
import task_graph


GATE_ARTIFACT_RULES = {
    "requirements_baseline": (
        "requirements-baseline",
        ("核心文档", "需求基线.md"),
    ),
    "route_selection": (
        "route-selection",
        ("过程产物", "路线评估"),
    ),
    "final_spec_approval": (
        "final-spec",
        ("最终产物", "最终规格.md"),
    ),
}


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

    conflicts = []
    collections = {}
    for collection_name in ("phases", "artifacts", "tasks", "evidence"):
        records = workflow.get(collection_name, [])
        if not isinstance(records, list):
            conflicts.append(
                _conflict(
                    "INVALID_COLLECTION",
                    "{} 必须是记录列表，当前类型为 {}。".format(
                        collection_name, type(records).__name__
                    ),
                    "暂停对账，恢复该集合为 JSON/YAML 列表后重新运行状态检查。",
                    collection=collection_name,
                    actual_type=type(records).__name__,
                )
            )
            collections[collection_name] = []
        else:
            collections[collection_name] = records
    conflicts.extend(
        _identity_conflicts_for_records("phases", collections["phases"], {})
    )
    shared_ids = {}
    for collection_name in ("artifacts", "tasks", "evidence"):
        conflicts.extend(
            _identity_conflicts_for_records(
                collection_name,
                collections[collection_name],
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


def _inside_root(path, storage_root):
    if storage_root is None:
        return True
    try:
        Path(path).resolve().relative_to(Path(storage_root).resolve())
    except (TypeError, ValueError):
        return False
    return True


def _artifact_contract_conflicts(
    artifact: Mapping[str, Any], storage_root=None
) -> list:
    artifact_id = artifact.get("id", "<unknown>")
    conflicts = []
    version = artifact.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        conflicts.append(
            _conflict(
                "ARTIFACT_VERSION",
                "产物 {} 缺少有效的正整数版本。".format(artifact_id),
                "为当前产物登记稳定版本，并重新绑定相关人工批准。",
                artifact_id=artifact_id,
            )
        )
    if artifact.get("currentness") != "current":
        conflicts.append(
            _conflict(
                "NONCURRENT_ARTIFACT",
                "产物 {} 不是当前有效版本。".format(artifact_id),
                "重新生成或复核产物，并将人工批准绑定到新的当前版本。",
                artifact_id=artifact_id,
            )
        )
    path = artifact.get("path")
    if (
        not isinstance(path, str)
        or not os.path.isabs(path)
        or not Path(path).is_file()
        or not _inside_root(path, storage_root)
    ):
        conflicts.append(
            _conflict(
                "ARTIFACT_PATH",
                "产物 {} 没有可读取的真实绝对文件路径。".format(artifact_id),
                "在当前工作流目录保存产物，登记真实绝对路径后重新对账。",
                artifact_id=artifact_id,
                path=path,
            )
        )
    return conflicts


def _strict_task_contract_conflicts(task, workflow_root, evidence_index, workflow):
    task_id = task.get("id", "<unknown>")
    conflicts = []
    required_lists = (
        "depends_on",
        "blockers",
        "trace_ids",
        "acceptance_ids",
        "allowed_paths",
        "forbidden_paths",
        "write_paths",
        "shared_contracts",
        "migrations",
        "generated_files",
    )
    for field in required_lists:
        value = task.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            conflicts.append(
                _conflict(
                    "TASK_CONTRACT",
                    "任务 {} 的 {} 不是字符串列表。".format(task_id, field),
                    "补齐自包含任务包字段后重新登记任务。",
                    task_id=task_id,
                    field=field,
                )
            )
    for field in ("trace_ids", "acceptance_ids", "allowed_paths", "write_paths"):
        if isinstance(task.get(field), list) and not task[field]:
            conflicts.append(
                _conflict(
                    "TASK_CONTRACT",
                    "任务 {} 的 {} 不能为空。".format(task_id, field),
                    "补齐真实追踪和授权范围后重新登记任务。",
                    task_id=task_id,
                    field=field,
                )
            )
    for field in (
        "status",
        "currentness",
        "parallel_group",
        "git_baseline",
        "worktree",
        "branch",
        "task_package_path",
        "startup_prompt_path",
        "output_path",
    ):
        if not isinstance(task.get(field), str) or not task[field].strip():
            conflicts.append(
                _conflict(
                    "TASK_CONTRACT",
                    "任务 {} 缺少 {}。".format(task_id, field),
                    "补齐任务执行与隔离字段后重新对账。",
                    task_id=task_id,
                    field=field,
                )
            )
    package_path = task.get("task_package_path")
    if (
        isinstance(package_path, str)
        and (
            not _inside_root(package_path, workflow_root)
            or not Path(package_path).is_file()
        )
    ):
        conflicts.append(
            _conflict(
                "TASK_PACKAGE_PATH",
                "任务 {} 的本地任务包不存在或不属于当前工作流。".format(task_id),
                "在当前工作流的过程产物/任务交接中生成自包含任务包。",
                task_id=task_id,
            )
        )
    startup_path = task.get("startup_prompt_path")
    if (
        isinstance(startup_path, str)
        and (
            not _inside_root(startup_path, workflow_root)
            or not Path(startup_path).is_file()
        )
    ):
        conflicts.append(
            _conflict(
                "TASK_STARTUP_PROMPT",
                "任务 {} 的本地启动提示词不存在或不属于当前工作流。".format(
                    task_id
                ),
                "在当前工作流的过程产物/任务交接中生成短启动提示词。",
                task_id=task_id,
            )
        )
    if task.get("status") == "completed":
        evidence_ids = task.get("evidence")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            conflicts.append(
                _conflict(
                    "TASK_EVIDENCE",
                    "任务 {} 声称完成但没有证据 ID。".format(task_id),
                    "通过受保护的 task-transition 登记当前基线证据。",
                    task_id=task_id,
                )
            )
        else:
            for evidence_id in evidence_ids:
                evidence_record = evidence_index.get(evidence_id)
                if evidence_record is None:
                    conflicts.append(
                        _conflict(
                            "TASK_EVIDENCE",
                            "任务 {} 引用了不存在的证据 {}。".format(
                                task_id, evidence_id
                            ),
                            "重新运行验证并登记真实证据。",
                            task_id=task_id,
                            evidence_id=evidence_id,
                        )
                    )
                    continue
                if task_id not in evidence_record.get("tasks", ()):
                    conflicts.append(
                        _conflict(
                            "TASK_EVIDENCE",
                            "任务 {} 的证据 {} 未回链当前任务。".format(
                                task_id, evidence_id
                            ),
                            "重新登记 tasks 包含当前 TASK-ID 的验证证据。",
                            task_id=task_id,
                            evidence_id=evidence_id,
                        )
                    )
                    continue
                report = validate_evidence(
                    evidence_record,
                    current_baseline=workflow.get("_validation_baseline"),
                    current_time=workflow.get("_validation_time"),
                    require_output_exists=True,
                )
                conflicts.extend(report["conflicts"])
        output_path = task.get("output_path")
        if not isinstance(output_path, str) or not Path(output_path).is_file():
            conflicts.append(
                _conflict(
                    "TASK_REPORT",
                    "任务 {} 的完成报告不存在。".format(task_id),
                    "把实施报告写入当前工作流后再完成任务。",
                    task_id=task_id,
                )
            )
    return conflicts


def _gate_binding_conflicts(workflow, artifacts, storage_root=None):
    conflicts = []
    gates = workflow.get("gates", {})
    if not isinstance(gates, Mapping):
        return conflicts
    latest = {}
    ledger = workflow.get("ledger", ())
    if isinstance(ledger, list):
        try:
            state.validate_ledger(ledger)
        except (ValueError, state.LedgerContractError):
            ledger = []
        for item in ledger:
            if (
                isinstance(item, Mapping)
                and item.get("type") in ("DEC", "CHG")
                and isinstance(item.get("id"), str)
            ):
                latest[item["id"]] = item
    for gate_name, gate_record in gates.items():
        if not isinstance(gate_record, Mapping):
            continue
        try:
            state.validate_gate_contract(gate_name, gate_record)
        except (ValueError, state.StateContractError) as error:
            conflicts.append(
                _conflict(
                    "INVALID_GATE_BINDING",
                    "人工门禁 {} 的批准记录无效：{}".format(gate_name, error),
                    "恢复真实决策记录并把批准绑定到存在的当前产物版本。",
                    gate=gate_name,
                )
            )
            continue
        approval_id = gate_record["approval_id"]
        artifact_versions = gate_record["artifact_versions"]
        approval_record = latest.get(approval_id)
        binding_valid = (
            approval_record is not None
            and approval_record.get("status") == "approved"
            and approval_record.get("approved_by") == "user"
            and approval_record.get("gate") == gate_name
            and approval_record.get("artifact_versions") == artifact_versions
        )
        for artifact_id, expected_version in artifact_versions.items():
            artifact = artifacts.get(artifact_id)
            expected_kind, expected_path_parts = GATE_ARTIFACT_RULES[gate_name]
            artifact_path = (
                Path(artifact.get("path")).resolve()
                if isinstance(artifact, Mapping)
                and isinstance(artifact.get("path"), str)
                else None
            )
            path_parts = artifact_path.parts if artifact_path is not None else ()
            if gate_name == "route_selection":
                path_matches = any(
                    tuple(path_parts[index:index + len(expected_path_parts)])
                    == expected_path_parts
                    for index in range(len(path_parts) - len(expected_path_parts))
                )
            else:
                path_matches = tuple(path_parts[-len(expected_path_parts):]) == expected_path_parts
            if (
                artifact is None
                or artifact.get("version") != expected_version
                or artifact.get("status") != "completed"
                or artifact.get("currentness") != "current"
                or artifact.get("kind") != expected_kind
                or not path_matches
                or approval_id not in artifact.get("decisions", ())
                or _artifact_contract_conflicts(artifact, storage_root)
            ):
                binding_valid = False
                break
        if not binding_valid:
            conflicts.append(
                _conflict(
                    "INVALID_GATE_BINDING",
                    "人工门禁 {} 未绑定到真实决策和精确的当前产物版本。".format(
                        gate_name
                    ),
                    "确认 DEC/CHG 记录、产物 ID、版本、状态和决策关联后重新批准。",
                    gate=gate_name,
                    approval_id=approval_id,
                )
            )
    return conflicts


def reconcile_workflow(
    workflow: Mapping[str, Any],
    current_baseline: str = None,
    current_time: str = None,
    storage_root: str = None,
) -> Dict[str, Any]:
    """Report state/artifact contradictions without changing the workflow."""

    conflicts = identity_invariant_conflicts(workflow)
    if conflicts:
        return {"valid": False, "conflicts": conflicts}
    ledger = workflow.get("ledger", [])
    if not isinstance(ledger, list):
        conflicts.append(
            _conflict(
                "INVALID_COLLECTION",
                "ledger 必须是版本连续的记录列表。",
                "恢复核心决策账本和 state 中的 Ledger 列表后重新对账。",
                collection="ledger",
            )
        )
    else:
        try:
            state.validate_ledger(ledger)
        except (ValueError, state.LedgerContractError) as error:
            conflicts.append(
                _conflict(
                    "LEDGER_CONTRACT",
                    "决策账本版本或身份冲突：{}".format(error),
                    "保留全部历史版本，修复 ID 与连续版本后重新对账。",
                )
            )
    artifacts = _records_by_id(workflow.get("artifacts", ()))
    evidence = _records_by_id(workflow.get("evidence", ()))
    ledger_latest = {}
    for ledger_record in workflow.get("ledger", ()):
        if isinstance(ledger_record, Mapping) and isinstance(
            ledger_record.get("id"), str
        ):
            ledger_latest[ledger_record["id"]] = ledger_record
    validation_workflow = dict(workflow)
    validation_workflow["_validation_time"] = current_time
    validation_workflow["_validation_baseline"] = current_baseline
    graph_report = task_graph.validate_dag(workflow.get("tasks", ()))
    conflicts.extend(graph_report.get("conflicts", ()))
    frontier = (
        task_graph.calculate_frontier(workflow.get("tasks", ())).get("frontier", [])
        if graph_report.get("valid")
        else []
    )
    conflicts.extend(_gate_binding_conflicts(workflow, artifacts, storage_root))
    if workflow.get("schema_version") is not None:
        for task in workflow.get("tasks", ()):
            if isinstance(task, Mapping):
                conflicts.extend(
                    _strict_task_contract_conflicts(
                        task, storage_root, evidence, validation_workflow
                    )
                )
    phase_records = workflow.get("phases", ())
    phase_ids = {
        item.get("id")
        for item in phase_records
        if isinstance(item, Mapping)
    }
    if phase_ids.issuperset(state.WORKFLOW_PHASES):
        completed_prefix = True
        for phase_id in state.WORKFLOW_PHASES:
            phase = next(item for item in phase_records if item.get("id") == phase_id)
            status = phase.get("status")
            if status != "pending" and not completed_prefix:
                conflicts.append(
                    _conflict(
                        "PHASE_ORDER",
                        "阶段 {} 已进入，但前序阶段尚未完成或跳过。".format(
                            phase_id
                        ),
                        "退回该阶段，按顺序完成前置阶段和门禁后再继续。",
                        phase_id=phase_id,
                    )
                )
            if status not in ("completed", "skipped"):
                completed_prefix = False
    for task in workflow.get("tasks", ()):
        if not isinstance(task, Mapping):
            continue
        for field in ("task_package_path", "startup_prompt_path", "output_path"):
            if field in task and not _inside_root(task.get(field), storage_root):
                conflicts.append(
                    _conflict(
                        "TASK_OUTPUT_PATH",
                        "任务 {} 的 {} 不在 Grill Harness 工作流目录。".format(
                            task.get("id", "<unknown>"), field
                        ),
                        "把任务包和报告路径改到当前 ~/.grill-harness/ 工作流目录。",
                        task_id=task.get("id"),
                        field=field,
                    )
                )
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
        if phase.get("status") == "skipped" and phase_id in state.WORKFLOW_PHASES:
            if phase_id not in state.OPTIONAL_PHASES:
                conflicts.append(
                    _conflict(
                        "REQUIRED_PHASE_SKIPPED",
                        "必需阶段 {} 不允许标记为 skipped。".format(phase_id),
                        "恢复必需阶段并完成其最小产物；不要在运行时把它改成可选。",
                        phase_id=phase_id,
                    )
                )
            approval_id = phase.get("skip_approval_id")
            approval_record = ledger_latest.get(approval_id)
            if not (
                isinstance(approval_record, Mapping)
                and approval_record.get("status") == "approved"
                and approval_record.get("approved_by") == "user"
                and approval_record.get("gate") == "skip:{}".format(phase_id)
            ):
                conflicts.append(
                    _conflict(
                        "SKIP_APPROVAL",
                        "阶段 {} 被跳过但没有真实用户批准记录。".format(phase_id),
                        "登记绑定该阶段的用户 DEC/CHG 后再执行 skipped 迁移。",
                        phase_id=phase_id,
                    )
                )
        if phase.get("status") != "completed":
            continue
        phase_artifacts = phase.get("artifacts", ())
        phase_evidence = phase.get("evidence", ())
        if not isinstance(phase_artifacts, list) or not isinstance(phase_evidence, list):
            continue
        for artifact_id in phase_artifacts:
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
            else:
                conflicts.extend(
                    _artifact_contract_conflicts(artifact, storage_root)
                )
        for evidence_id in phase_evidence:
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
            else:
                conflicts.extend(
                    validate_evidence(
                        evidence_record,
                        current_baseline=current_baseline,
                        current_time=current_time,
                        require_output_exists=True,
                    )["conflicts"]
                )
                if not _inside_root(evidence_record.get("output_path"), storage_root):
                    conflicts.append(
                        _conflict(
                            "EVIDENCE_OUTPUT_PATH",
                            "证据 {} 的输出不在 Grill Harness 工作流目录。".format(
                                evidence_id
                            ),
                            "把原始验证输出保存到当前 ~/.grill-harness/ 工作流目录。",
                            evidence_id=evidence_id,
                        )
                    )
    return {
        "valid": not conflicts,
        "conflicts": conflicts,
        "frontier": frontier,
        "task_graph": graph_report,
    }


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


def _parse_aware_iso8601(value: Any):
    if not _nonempty_string(value):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def validate_evidence(
    evidence: Mapping[str, Any],
    current_baseline: str = None,
    current_time: str = None,
    require_output_exists: bool = False,
) -> Dict[str, Any]:
    """Validate whether one evidence record can support a completion claim."""

    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "conflicts": [
                _conflict(
                    "INVALID_EVIDENCE_RECORD",
                    "证据记录不是可识别的映射，无法验证其来源和当前性。",
                    "恢复原始证据结构并补齐稳定字段后重新验证。",
                )
            ],
        }
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
    parsed_times = {}
    for field in ("executed_at", "validated_at", "expires_at"):
        parsed = _parse_aware_iso8601(evidence.get(field))
        if parsed is None:
            conflicts.append(
                _conflict(
                    "EVIDENCE_TIME",
                    "证据 {} 的 {} 不是带时区的 ISO-8601 时间。".format(evidence_id, field),
                    "记录可解析且带 UTC 偏移的真实时间后重新验证。",
                    evidence_id=evidence_id,
                    field=field,
                )
            )
        else:
            parsed_times[field] = parsed
    parsed_current_time = _parse_aware_iso8601(current_time)
    if parsed_current_time is None:
        conflicts.append(
            _conflict(
                "EVIDENCE_CURRENT_TIME",
                "证据验证缺少显式、带时区的当前时间。",
                "由调用方提供确定的 ISO-8601 当前时间，不要读取隐式系统时钟。",
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
    elif require_output_exists and not Path(output_path).is_file():
        conflicts.append(
            _conflict(
                "EVIDENCE_OUTPUT_PATH",
                "证据 {} 的原始输出文件不存在。".format(evidence_id),
                "保存真实命令输出并登记可读取的绝对路径后重新验收。",
                evidence_id=evidence_id,
                output_path=output_path,
            )
        )
    temporally_stale = False
    if parsed_current_time is not None and len(parsed_times) == 3:
        temporally_stale = (
            parsed_times["executed_at"] > parsed_times["validated_at"]
            or parsed_times["validated_at"] > parsed_current_time
            or parsed_current_time >= parsed_times["expires_at"]
        )
    if (
        evidence.get("status") != "valid"
        or evidence.get("currentness") != "current"
        or bool(evidence.get("stale_because"))
        or temporally_stale
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
    records: Iterable[Mapping[str, Any]],
    current_baseline: str = None,
    current_time: str = None,
) -> Dict[str, Any]:
    """Validate a collection without hiding which evidence record failed."""

    reports = []
    conflicts = []
    seen_ids = set()
    for evidence in records:
        evidence_id = evidence.get("id") if isinstance(evidence, Mapping) else None
        if _nonempty_string(evidence_id) and evidence_id in seen_ids:
            conflicts.append(
                _conflict(
                    "DUPLICATE_EVIDENCE_ID",
                    "证据集合存在重复 ID {}，不能以后写记录覆盖前一事实。".format(evidence_id),
                    "保留两条原始记录，由用户确认正确版本和替代关系。",
                    evidence_id=evidence_id,
                )
            )
        elif _nonempty_string(evidence_id):
            seen_ids.add(evidence_id)
        report = validate_evidence(
            evidence,
            current_baseline=current_baseline,
            current_time=current_time,
        )
        reports.append({"evidence_id": evidence_id, **report})
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
