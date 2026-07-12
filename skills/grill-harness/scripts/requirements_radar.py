"""Pure contracts for adaptive requirements-radar findings."""

import re
from collections.abc import Mapping, Sequence


RADAR_CATEGORIES = frozenset(
    ("clarification", "omission", "implication", "paradox", "analogue")
)
RADAR_STATUSES = frozenset(("open", "resolved", "superseded", "dismissed"))
BLOCKING_LEVELS = frozenset(("none", "implementation", "baseline"))
CONFIDENCE_LEVELS = frozenset(("low", "medium", "high"))
TRACE_ARTIFACTS = (
    "route_card",
    "repository_challenge",
    "final_spec",
    "tasks",
    "acceptance",
    "knowledge",
)
ANALOGUE_FIELDS = (
    "similarities",
    "differences",
    "reusable_parts",
    "non_reuse_reasons",
    "shared_contracts",
    "reusable_tests",
    "new_behavior",
)


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _is_radar_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"RAD-[0-9]{3,}", value))


def _string_list(value, allow_empty=False):
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


def validate_radar_record(record):
    """Validate one stable RAD finding without mutating it."""

    conflicts = []
    if not isinstance(record, Mapping):
        return _report([_conflict("record", "radar record must be a mapping")])
    if record.get("type") != "RAD" or not _is_radar_id(record.get("id")):
        conflicts.append(_conflict("id", "radar record requires a stable RAD-xxx id"))
    if record.get("category") not in RADAR_CATEGORIES:
        conflicts.append(_conflict("category", "unknown radar category"))
    if not isinstance(record.get("version"), int) or isinstance(
        record.get("version"), bool
    ) or record["version"] < 1:
        conflicts.append(_conflict("version", "radar version must be positive"))
    for field in ("summary", "impact", "owner"):
        if not _non_empty_string(record.get(field)):
            conflicts.append(_conflict(field, "{} must be non-empty".format(field)))
    if not _string_list(record.get("evidence")):
        conflicts.append(_conflict("evidence", "radar evidence must not be empty"))
    if record.get("confidence") not in CONFIDENCE_LEVELS:
        conflicts.append(_conflict("confidence", "unknown confidence level"))
    if record.get("blocking_level") not in BLOCKING_LEVELS:
        conflicts.append(_conflict("blocking_level", "unknown blocking level"))
    if record.get("status") not in RADAR_STATUSES:
        conflicts.append(_conflict("status", "unknown radar status"))
    risk_signals = record.get("risk_signals")
    if not isinstance(risk_signals, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, bool)
        for key, value in risk_signals.items()
    ):
        conflicts.append(
            _conflict("risk_signals", "risk signals must be a mapping of booleans")
        )
        derived_escalation = None
    else:
        derived_escalation = classify_escalation(risk_signals)["level"]
    escalation = record.get("escalation")
    if escalation not in ("low", "medium", "high"):
        conflicts.append(
            _conflict("escalation", "radar escalation must be low, medium, or high")
        )
    elif derived_escalation is not None and escalation != derived_escalation:
        conflicts.append(
            _conflict(
                "escalation",
                "radar escalation must match the level derived from risk signals",
            )
        )
    requirements = record.get("requirements")
    decisions = record.get("decisions")
    if not _string_list(requirements, allow_empty=True) or not _string_list(
        decisions, allow_empty=True
    ) or not (requirements or decisions):
        conflicts.append(
            _conflict(
                "traceability",
                "radar record must link at least one requirement or decision",
            )
        )
    if derived_escalation == "high":
        investigation = record.get("investigation_plan")
        required = (
            "reason",
            "question",
            "role",
            "expected_output",
        )
        if not isinstance(investigation, Mapping):
            conflicts.append(
                _conflict(
                    "investigation_plan", "high risk requires an investigation plan"
                )
            )
        else:
            for field in required:
                if not _non_empty_string(investigation.get(field)):
                    conflicts.append(
                        _conflict(
                            "investigation_plan.{}".format(field),
                            "investigation {} must be non-empty".format(field),
                        )
                    )
            if not isinstance(investigation.get("blocks_baseline"), bool):
                conflicts.append(
                    _conflict(
                        "investigation_plan.blocks_baseline",
                        "investigation must state whether it blocks the baseline",
                    )
                )
            if investigation.get("agent_selection") != "needs_user":
                conflicts.append(
                    _conflict(
                        "investigation_plan.agent_selection",
                        "independent investigation agent selection must remain user controlled",
                    )
                )
    return _report(conflicts)


def classify_escalation(facts):
    """Classify scan facts using the design's bounded escalation rules."""

    facts = facts if isinstance(facts, Mapping) else {}
    high_signals = (
        "public_contract_change",
        "schema_change",
        "constraint_conflict",
        "impact_unknown",
        "high_rework_cost",
    )
    if any(facts.get(signal) for signal in high_signals):
        return {"level": "high", "independent_investigation": True}
    if facts.get("cross_module_call_chain") or facts.get(
        "multiple_inconsistent_precedents"
    ):
        return {"level": "medium", "independent_investigation": False}
    return {"level": "low", "independent_investigation": False}


def unresolved_baseline_blockers(records):
    """Return stable IDs whose latest version is an open baseline blocker."""

    latest = {}
    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        record_id = record.get("id")
        version = record.get("version")
        if not _is_radar_id(record_id):
            continue
        if not isinstance(version, int) or isinstance(version, bool):
            continue
        current = latest.get(record_id)
        if current is None or version > current.get("version", 0):
            latest[record_id] = record
    return sorted(
        record_id
        for record_id, record in latest.items()
        if record.get("blocking_level") == "baseline"
        and record.get("status") == "open"
    )


def validate_analogue_comparison(comparison):
    """Validate found candidates or honest not-found search evidence."""

    conflicts = []
    if not isinstance(comparison, Mapping):
        return _report([_conflict("comparison", "comparison must be a mapping")])
    status = comparison.get("status")
    if status == "not_found":
        if not _string_list(comparison.get("search_scope")):
            conflicts.append(
                _conflict("search_scope", "not-found comparison requires search scope")
            )
        if not _string_list(comparison.get("search_evidence")):
            conflicts.append(
                _conflict(
                    "search_evidence", "not-found comparison requires search evidence"
                )
            )
        return _report(conflicts)
    if status != "found":
        return _report([_conflict("status", "comparison status must be found or not_found")])
    candidates = comparison.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return _report([_conflict("candidates", "found comparison requires candidates")])
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            conflicts.append(
                _conflict("candidates", "candidate {} must be a mapping".format(index))
            )
            continue
        for field in ("path", "symbol"):
            if not _non_empty_string(candidate.get(field)):
                conflicts.append(
                    _conflict(field, "candidate {} requires {}".format(index, field))
                )
        for field in ANALOGUE_FIELDS:
            if not _string_list(candidate.get(field)):
                conflicts.append(
                    _conflict(field, "candidate {} requires {}".format(index, field))
                )
    return _report(conflicts)


def traceability_report(records, artifacts):
    """Report missing RAD links for each required downstream artifact class."""

    radar_ids = sorted(
        {
            record.get("id")
            for record in records or ()
            if isinstance(record, Mapping)
            and _is_radar_id(record.get("id"))
        }
    )
    artifacts = artifacts if isinstance(artifacts, Mapping) else {}
    missing = {}
    conflicts = []
    for artifact_name in TRACE_ARTIFACTS:
        artifact = artifacts.get(artifact_name, {})
        linked = artifact.get("radar_ids") if isinstance(artifact, Mapping) else None
        if not (
            isinstance(linked, Sequence)
            and not isinstance(linked, (str, bytes, bytearray, Mapping))
        ):
            conflicts.append(
                {
                    "artifact": artifact_name,
                    "field": "radar_ids",
                    "conflict": "artifact radar_ids must be a non-string sequence",
                }
            )
            continue
        invalid = [record_id for record_id in linked if not _is_radar_id(record_id)]
        if invalid:
            conflicts.append(
                {
                    "artifact": artifact_name,
                    "field": "radar_ids",
                    "conflict": "artifact radar_ids contain invalid stable IDs",
                }
            )
            continue
        absent = [record_id for record_id in radar_ids if record_id not in linked]
        if absent:
            missing[artifact_name] = absent
    return {"valid": not missing and not conflicts, "missing": missing, "conflicts": conflicts}


__all__ = [
    "classify_escalation",
    "traceability_report",
    "unresolved_baseline_blockers",
    "validate_analogue_comparison",
    "validate_radar_record",
]
