"""Deterministic task DAG, Frontier, and conservative conflict analysis."""

import itertools
import os
import posixpath
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


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


def _string_sequence(value: Any) -> Optional[List[str]]:
    if value is None:
        return []
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or isinstance(value, Mapping)
    ):
        return None
    items = list(value)
    if any(not isinstance(item, str) or not item.strip() for item in items):
        return None
    return items


def _task_dependencies(task: Mapping[str, Any]) -> Tuple[Optional[List[str]], bool]:
    depends_on = _string_sequence(task.get("depends_on"))
    blockers = _string_sequence(task.get("blockers"))
    if depends_on is None or blockers is None:
        return None, False
    if "depends_on" in task and "blockers" in task:
        if sorted(set(depends_on)) != sorted(set(blockers)):
            return None, True
    selected = blockers if "blockers" in task else depends_on
    return sorted(set(selected or [])), False


def _index_tasks(
    tasks: Iterable[Mapping[str, Any]],
) -> Tuple[Dict[str, Mapping[str, Any]], Dict[str, List[str]], List[Dict[str, Any]]]:
    indexed: Dict[str, Mapping[str, Any]] = {}
    dependencies: Dict[str, List[str]] = {}
    conflicts: List[Dict[str, Any]] = []
    for position, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            conflicts.append(
                _conflict(
                    "INVALID_TASK",
                    "任务图第 {} 条记录不是映射，无法安全调度。".format(position + 1),
                    "恢复任务记录结构，并补齐稳定任务 ID 后重新计算。",
                    position=position,
                )
            )
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            conflicts.append(
                _conflict(
                    "INVALID_TASK_ID",
                    "任务图第 {} 条记录缺少非空字符串 ID。".format(position + 1),
                    "补齐稳定且唯一的任务 ID 后重新计算。",
                    position=position,
                )
            )
            continue
        if task_id in indexed:
            conflicts.append(
                _conflict(
                    "DUPLICATE_TASK_ID",
                    "任务图存在重复 ID {}，不能用后写记录覆盖前一任务。".format(task_id),
                    "保留原始记录，由用户确认正确任务及替代关系。",
                    task_id=task_id,
                )
            )
            continue
        if "depends_on" not in task and "blockers" not in task:
            conflicts.append(
                _conflict(
                    "MISSING_BLOCKERS",
                    "任务 {} 未显式声明 depends_on 或 blockers，无法判断是否为根任务。".format(task_id),
                    "显式写入依赖字段；根任务使用空列表，不要依赖字段缺失的隐式含义。",
                    task_id=task_id,
                )
            )
            continue
        task_dependencies, contradictory_aliases = _task_dependencies(task)
        if task_dependencies is None:
            code = "CONTRADICTORY_BLOCKERS" if contradictory_aliases else "INVALID_BLOCKERS"
            conflicts.append(
                _conflict(
                    code,
                    "任务 {} 的 depends_on/blockers 不是一致的非空字符串 ID 序列。".format(task_id),
                    "统一依赖字段并保留真实阻塞边后重新计算。",
                    task_id=task_id,
                )
            )
            continue
        indexed[task_id] = task
        dependencies[task_id] = task_dependencies

    for task_id in sorted(dependencies):
        for dependency_id in dependencies[task_id]:
            if dependency_id == task_id:
                conflicts.append(
                    _conflict(
                        "SELF_DEPENDENCY",
                        "任务 {} 依赖自身，无法进入可执行 Frontier。".format(task_id),
                        "移除自依赖或拆分任务，并重新确认阻塞边。",
                        task_id=task_id,
                    )
                )
            elif dependency_id not in indexed:
                conflicts.append(
                    _conflict(
                        "UNKNOWN_DEPENDENCY",
                        "任务 {} 引用了不存在的依赖 {}。".format(task_id, dependency_id),
                        "补建真实依赖任务或修正依赖 ID 后重新计算。",
                        task_id=task_id,
                        dependency_id=dependency_id,
                    )
                )
    return indexed, dependencies, conflicts


def _cyclic_task_ids(dependencies: Mapping[str, Sequence[str]]) -> List[str]:
    state: Dict[str, int] = {}
    stack: List[str] = []
    cyclic: Set[str] = set()

    def visit(task_id: str) -> None:
        state[task_id] = 1
        stack.append(task_id)
        for dependency_id in dependencies[task_id]:
            if dependency_id not in dependencies:
                continue
            dependency_state = state.get(dependency_id, 0)
            if dependency_state == 0:
                visit(dependency_id)
            elif dependency_state == 1:
                cyclic.update(stack[stack.index(dependency_id):])
        stack.pop()
        state[task_id] = 2

    for task_id in sorted(dependencies):
        if state.get(task_id, 0) == 0:
            visit(task_id)
    return sorted(cyclic)


def validate_dag(tasks: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a deterministic, machine-readable DAG validation report."""

    task_list = list(tasks)
    indexed, dependencies, conflicts = _index_tasks(task_list)
    if not conflicts:
        cyclic = _cyclic_task_ids(dependencies)
        if cyclic:
            conflicts.append(
                _conflict(
                    "TASK_GRAPH_CYCLE",
                    "任务图存在循环依赖：{}。".format("、".join(cyclic)),
                    "暂停受影响任务，删除或重构至少一条循环阻塞边。",
                    task_ids=cyclic,
                )
            )

    topological_order: List[str] = []
    if not conflicts:
        indegree = {task_id: len(dependencies[task_id]) for task_id in indexed}
        dependents: Dict[str, List[str]] = defaultdict(list)
        for task_id, dependency_ids in dependencies.items():
            for dependency_id in dependency_ids:
                dependents[dependency_id].append(task_id)
        ready = sorted(task_id for task_id, count in indegree.items() if count == 0)
        while ready:
            task_id = ready.pop(0)
            topological_order.append(task_id)
            for dependent_id in sorted(dependents[task_id]):
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    ready.append(dependent_id)
                    ready.sort()
    return {
        "valid": not conflicts,
        "topological_order": topological_order,
        "conflicts": conflicts,
    }


def calculate_frontier(tasks: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return pending tasks whose explicit blockers are completed and current."""

    task_list = list(tasks)
    graph_report = validate_dag(task_list)
    if not graph_report["valid"]:
        return {
            "valid": False,
            "frontier": [],
            "blocked": [],
            "conflicts": graph_report["conflicts"],
        }
    indexed, dependencies, _ = _index_tasks(task_list)
    frontier = []
    blocked = []
    for task_id in sorted(indexed):
        task = indexed[task_id]
        if task.get("status") != "pending" or task.get("currentness") == "stale":
            continue
        unmet = [
            dependency_id
            for dependency_id in dependencies[task_id]
            if indexed[dependency_id].get("status") != "completed"
            or indexed[dependency_id].get("currentness") != "current"
        ]
        if unmet:
            blocked.append({"task_id": task_id, "blockers": unmet})
        else:
            frontier.append(task_id)
    return {
        "valid": True,
        "frontier": frontier,
        "blocked": blocked,
        "conflicts": [],
    }


def _normalized_values(task: Mapping[str, Any], field: str) -> Set[str]:
    values = _string_sequence(task.get(field))
    if values is None:
        return set()
    return {value.strip() for value in values}


def _normalize_write_path(path: str) -> str:
    normalized = posixpath.normpath(path.replace("\\", "/"))
    return normalized.rstrip("/") or "."


def _paths_overlap(left: str, right: str) -> bool:
    normalized_left = _normalize_write_path(left)
    normalized_right = _normalize_write_path(right)
    if normalized_left == "." or normalized_right == ".":
        return True
    left_parts = normalized_left.split("/")
    right_parts = normalized_right.split("/")
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def analyze_task_conflict(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> Dict[str, Any]:
    """Distinguish logical parallelism from safe parallel execution."""

    task_ids = sorted([str(left.get("id", "<unknown>")), str(right.get("id", "<unknown>"))])
    content_conflicts: List[Dict[str, Any]] = []
    conflict_fields = ("write_paths", "shared_contracts", "migrations", "generated_files")
    for task in (left, right):
        for field in conflict_fields:
            if field not in task or _string_sequence(task.get(field)) is None:
                content_conflicts.append(
                    _conflict(
                        "INVALID_CONFLICT_FIELD",
                        "任务 {} 的冲突字段 {} 不是字符串 ID 序列，无法证明并行安全。".format(
                            task.get("id", "<unknown>"), field
                        ),
                        "修复该字段并重新执行冲突分析；在此之前将任务降级为串行。",
                        task_id=task.get("id"),
                        field=field,
                    )
                )
    left_paths = sorted(_normalized_values(left, "write_paths"))
    right_paths = sorted(_normalized_values(right, "write_paths"))
    overlaps = sorted(
        {"{} <> {}".format(a, b) for a in left_paths for b in right_paths if _paths_overlap(a, b)}
    )
    if overlaps:
        content_conflicts.append(
            _conflict(
                "SHARED_WRITE_PATH",
                "任务 {} 的预计写入路径重叠。".format(" 与 ".join(task_ids)),
                "拆分写入范围、调整顺序，或将任务降级为串行执行。",
                task_ids=task_ids,
                overlaps=overlaps,
            )
        )

    for field, code, label, recovery in (
        ("shared_contracts", "SHARED_CONTRACT", "共享契约", "明确契约所有者和变更顺序后串行执行。"),
        ("migrations", "SHARED_MIGRATION", "迁移", "建立 expand–migrate–contract 顺序并串行执行。"),
        ("generated_files", "SHARED_GENERATED_FILE", "生成文件", "指定单一生成者并在生成后重新检查真实 diff。"),
    ):
        shared = sorted(_normalized_values(left, field).intersection(_normalized_values(right, field)))
        if shared:
            content_conflicts.append(
                _conflict(
                    code,
                    "任务 {} 同时修改{}：{}。".format(
                        " 与 ".join(task_ids), label, "、".join(shared)
                    ),
                    recovery,
                    task_ids=task_ids,
                    shared=shared,
                )
            )

    parallel_candidate = not content_conflicts
    isolation_conflicts: List[Dict[str, Any]] = []
    if parallel_candidate:
        left_worktree = left.get("worktree")
        right_worktree = right.get("worktree")
        if (
            not isinstance(left_worktree, str)
            or not left_worktree.strip()
            or not isinstance(right_worktree, str)
            or not right_worktree.strip()
            or os.path.normcase(os.path.normpath(left_worktree))
            == os.path.normcase(os.path.normpath(right_worktree))
        ):
            isolation_conflicts.append(
                _conflict(
                    "WORKTREE_NOT_DISTINCT",
                    "任务 {} 没有使用不同的 worktree，不能同时写入。".format(" 与 ".join(task_ids)),
                    "为每个任务建立独立 worktree；若环境不支持则降级为串行。",
                    task_ids=task_ids,
                )
            )
        left_branch = left.get("branch")
        right_branch = right.get("branch")
        if (
            not isinstance(left_branch, str)
            or not left_branch.strip()
            or not isinstance(right_branch, str)
            or not right_branch.strip()
            or left_branch == right_branch
        ):
            isolation_conflicts.append(
                _conflict(
                    "BRANCH_NOT_DISTINCT",
                    "任务 {} 没有使用不同的分支，无法隔离提交历史。".format(" 与 ".join(task_ids)),
                    "为每个 worktree 绑定独立分支，或将任务降级为串行。",
                    task_ids=task_ids,
                )
            )
    conflicts = content_conflicts + isolation_conflicts
    return {
        "task_ids": task_ids,
        "parallel_candidate": parallel_candidate,
        "executable_parallel": parallel_candidate and not isolation_conflicts,
        "conflicts": conflicts,
    }


def parallel_candidates(tasks: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return deterministic safe pairs from the current task Frontier."""

    task_list = list(tasks)
    frontier_report = calculate_frontier(task_list)
    if not frontier_report["valid"]:
        return {
            "valid": False,
            "frontier": [],
            "candidates": [],
            "rejected": [],
            "conflicts": frontier_report["conflicts"],
        }
    indexed = {task["id"]: task for task in task_list}
    candidates = []
    rejected = []
    for left_id, right_id in itertools.combinations(frontier_report["frontier"], 2):
        report = analyze_task_conflict(indexed[left_id], indexed[right_id])
        if report["executable_parallel"]:
            candidates.append(report)
        else:
            rejected.append(report)
    return {
        "valid": True,
        "frontier": frontier_report["frontier"],
        "candidates": candidates,
        "rejected": rejected,
        "conflicts": [],
    }


frontier = calculate_frontier
analyze_conflicts = analyze_task_conflict


__all__ = [
    "analyze_conflicts",
    "analyze_task_conflict",
    "calculate_frontier",
    "frontier",
    "parallel_candidates",
    "validate_dag",
]
