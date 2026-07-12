"""Deterministic failure classification and review-convergence policy."""

import hashlib
import json
from collections.abc import Mapping, Sequence


FAILURE_CLASSES = frozenset(
    (
        "implementation_failure",
        "route_failure",
        "evidence_failure",
        "workflow_integrity_failure",
    )
)
DEFAULT_ATTEMPT_THRESHOLD = 3
REPAIR_MODES = frozenset(("ordinary", "recovery", "route_selection", "reconcile"))


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _string_list(value, *, allow_empty=False):
    if isinstance(value, str):
        values = [value]
    elif (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray, Mapping))
    ):
        values = list(value)
    else:
        raise ValueError("failure fingerprint fields must be strings or string lists")
    if any(not _non_empty_string(item) for item in values):
        raise ValueError("failure fingerprint fields must contain non-empty strings")
    normalized = sorted(set(item.strip() for item in values))
    if not allow_empty and not normalized:
        raise ValueError("failure fingerprint field must not be empty")
    return normalized


def issue_fingerprint(
    issue_or_facts,
    failed_acceptance=None,
    failed_command=None,
    git_baseline=None,
):
    """Hash only stable issue, failed check, and Git-baseline facts."""

    if isinstance(issue_or_facts, Mapping):
        facts = issue_or_facts
        issue_id = facts.get("issue_id", facts.get("id"))
        failed_acceptance = facts.get(
            "failed_acceptance",
            facts.get("failed_acceptance_ids", failed_acceptance),
        )
        failed_command = facts.get(
            "failed_command",
            facts.get("failed_commands", failed_command),
        )
        git_baseline = facts.get(
            "originating_baseline", facts.get("git_baseline", git_baseline)
        )
    else:
        issue_id = issue_or_facts
    if not _non_empty_string(issue_id):
        raise ValueError("failure fingerprint requires a stable issue_id")
    if not _non_empty_string(git_baseline):
        raise ValueError("failure fingerprint requires the current Git baseline")
    acceptance = _string_list(failed_acceptance or (), allow_empty=True)
    commands = _string_list(failed_command or (), allow_empty=True)
    if not acceptance and not commands:
        raise ValueError("failure fingerprint requires a failed acceptance or command")
    payload = {
        "issue_id": issue_id.strip(),
        "failed_acceptance": acceptance,
        "failed_command": commands,
        "git_baseline": git_baseline.strip(),
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return "FAIL-{}".format(digest[:16])


def validate_threshold_override(
    override,
    ledger=(),
    *,
    fingerprint=None,
    issue_id=None,
):
    """Validate an explicit user-approved DEC/CHG threshold change."""

    conflicts = []
    if not isinstance(override, Mapping):
        return {
            "valid": False,
            "threshold": None,
            "approval_id": None,
            "conflicts": [
                {
                    "field": "override",
                    "conflict": "threshold override must be a mapping",
                }
            ],
        }
    threshold = override.get("threshold")
    if (
        not isinstance(threshold, int)
        or isinstance(threshold, bool)
        or threshold <= DEFAULT_ATTEMPT_THRESHOLD
    ):
        conflicts.append(
            {
                "field": "threshold",
                "conflict": "threshold override must be greater than the default threshold",
            }
        )
    reason = override.get("reason")
    if not _non_empty_string(reason):
        conflicts.append(
            {
                "field": "reason",
                "conflict": "threshold override requires a recorded reason",
            }
        )
    approval_id = override.get("approval_id", override.get("id"))
    fingerprint = fingerprint or override.get("failure_fingerprint")
    issue_id = issue_id or override.get("issue_id")
    approval = None
    if isinstance(ledger, Sequence) and not isinstance(
        ledger, (str, bytes, bytearray, Mapping)
    ):
        approval = next(
            (
                item
                for item in reversed(list(ledger))
                if isinstance(item, Mapping) and item.get("id") == approval_id
            ),
            None,
        )
    approval_type = approval.get("type") if isinstance(approval, Mapping) else None
    valid_prefix = (
        isinstance(approval_id, str)
        and any(
            approval_id.startswith("{}-".format(prefix))
            for prefix in ("DEC", "CHG")
        )
    )
    if not (
        isinstance(approval, Mapping)
        and approval_type in {"DEC", "CHG"}
        and valid_prefix
        and approval_id == approval.get("id")
        and approval.get("status") == "approved"
        and approval.get("approved_by") == "user"
        and approval_id.startswith("{}-".format(approval_type))
    ):
        conflicts.append(
            {
                "field": "approval_id",
                "conflict": "threshold override requires a persisted user-approved DEC/CHG",
            }
        )
    elif not (
        _non_empty_string(fingerprint)
        and _non_empty_string(issue_id)
        and approval.get("failure_fingerprint") == fingerprint
        and approval.get("issue_id") == issue_id
        and approval.get("approved_threshold") == threshold
        and approval.get("reason") == (
            reason.strip() if _non_empty_string(reason) else None
        )
    ):
        conflicts.append(
            {
                "field": "approval_binding",
                "conflict": (
                    "threshold approval must exactly bind the failure fingerprint, "
                    "issue, approved threshold, and reason"
                ),
            }
        )
    return {
        "valid": not conflicts,
        "threshold": threshold if not conflicts else None,
        "approval_id": approval_id,
        "reason": reason.strip() if _non_empty_string(reason) else reason,
        "conflicts": conflicts,
    }


def record_attempt(history, failure=None, *, threshold_override=None, ledger=(), **facts):
    """Append one immutable attempt record and return its bounded next action."""

    if not isinstance(history, Sequence) or isinstance(
        history, (str, bytes, bytearray, Mapping)
    ):
        raise ValueError("failure attempt history must be a list")
    existing = list(history)
    if any(not isinstance(item, Mapping) for item in existing):
        raise ValueError("failure attempt history entries must be mappings")
    if failure is None:
        failure = facts
    elif not isinstance(failure, Mapping):
        raise ValueError("failure attempt facts must be a mapping")
    elif facts:
        failure = dict(failure, **facts)
    else:
        failure = dict(failure)
    failure_class = failure.get("failure_class")
    if failure_class not in FAILURE_CLASSES:
        raise ValueError("unknown failure class: {}".format(failure_class))
    originating_baseline = failure.get(
        "originating_baseline", failure.get("git_baseline")
    )
    current_baseline = failure.get(
        "current_baseline", failure.get("observed_baseline", originating_baseline)
    )
    failure["originating_baseline"] = originating_baseline
    failure["current_baseline"] = current_baseline
    fingerprint = issue_fingerprint(failure)
    supplied_fingerprint = failure.get("fingerprint")
    if supplied_fingerprint is not None and supplied_fingerprint != fingerprint:
        raise ValueError(
            "failure fingerprint must match the structured issue/check/baseline facts"
        )
    matching = [item for item in existing if item.get("fingerprint") == fingerprint]
    if any(item.get("failure_class") != failure_class for item in matching):
        raise ValueError("failure class cannot change inside one fingerprint chain")
    if any(issue_fingerprint(item) != fingerprint for item in matching):
        raise ValueError("failure history fingerprint contradicts structured chain facts")
    if [item.get("attempt_count") for item in matching] != list(
        range(1, len(matching) + 1)
    ):
        raise ValueError("failure attempt history must be contiguous in persistence order")
    attempt_count = len(matching) + 1
    threshold = DEFAULT_ATTEMPT_THRESHOLD
    override_report = None
    if threshold_override is not None:
        override_report = validate_threshold_override(
            threshold_override,
            ledger,
            fingerprint=fingerprint,
            issue_id=failure.get("issue_id", failure.get("id")),
        )
        if not override_report["valid"]:
            raise ValueError(override_report["conflicts"][0]["conflict"])
        threshold = override_report["threshold"]
    action = next_action(
        failure_class,
        attempt_count=attempt_count,
        threshold=threshold,
        review_comments=failure.get("review_comments", ()),
        goals_satisfied=failure.get("goals_satisfied", True),
        test_evidence_satisfied=failure.get("test_evidence_satisfied", True),
        unresolved_route_issue=failure.get("unresolved_route_issue", False),
    )
    acceptance = _string_list(
        failure.get("failed_acceptance", failure.get("failed_acceptance_ids", ())),
        allow_empty=True,
    )
    commands = _string_list(
        failure.get("failed_command", failure.get("failed_commands", ())),
        allow_empty=True,
    )
    evidence = _string_list(failure.get("evidence", ()), allow_empty=True)
    record = {
        "failure_class": failure_class,
        "fingerprint": fingerprint,
        "issue_id": failure.get("issue_id", failure.get("id")),
        "failed_acceptance": acceptance,
        "failed_command": commands,
        "originating_baseline": originating_baseline,
        "current_baseline": current_baseline,
        "git_baseline": originating_baseline,
        "attempt_count": attempt_count,
        "attempt_history": [
            {
                "attempt_count": item.get("attempt_count"),
                "action": item.get("action"),
                "evidence": list(item.get("evidence", ())),
            }
            for item in existing
            if item.get("fingerprint") == fingerprint
        ],
        "evidence": evidence,
        "action": action["action"],
        "ordinary_repair_allowed": action["ordinary_repair_allowed"],
        "recommended_entry": action["recommended_entry"],
        "threshold": threshold,
        "threshold_override": (
            {
                "approval_id": override_report["approval_id"],
                "reason": override_report["reason"],
            }
            if override_report is not None
            else None
        ),
        "stop_condition": (
            "stop ordinary repair and require grh-recover"
            if action["action"] == "recover_required"
            else "stop if the failure class or approved scope changes"
        ),
    }
    updated_history = existing + [record]
    return dict(
        action,
        fingerprint=fingerprint,
        attempt_count=attempt_count,
        record=record,
        history=updated_history,
    )


def review_convergence(
    review_comments,
    *,
    goals_satisfied,
    test_evidence_satisfied,
    unresolved_route_issue,
):
    if not isinstance(review_comments, Sequence) or isinstance(
        review_comments, (str, bytes, bytearray, Mapping)
    ):
        raise ValueError("review comments must be a list")
    if not isinstance(goals_satisfied, bool) or not isinstance(
        test_evidence_satisfied, bool
    ) or not isinstance(unresolved_route_issue, bool):
        raise ValueError("review convergence facts must be booleans")
    unresolved = []
    optional = []
    missing_evidence = []
    closed_statuses = {"resolved", "closed", "fixed", "rejected", "invalid"}
    for index, comment in enumerate(review_comments):
        if not isinstance(comment, Mapping):
            raise ValueError("review comment {} must be a mapping".format(index))
        comment_id = comment.get("id")
        if not _non_empty_string(comment_id):
            raise ValueError("review comments require stable IDs")
        classification = comment.get(
            "classification", comment.get("disposition", comment.get("severity"))
        )
        status = comment.get("status", "open")
        if classification in {"optional", "optional_optimization", "non_blocking"}:
            if status not in closed_statuses:
                optional.append(comment_id)
        elif classification == "blocking":
            if status not in closed_statuses:
                unresolved.append(comment_id)
        elif classification == "must_fix":
            if status not in closed_statuses:
                unresolved.append(comment_id)
            elif not _string_list(comment.get("evidence", ()), allow_empty=True):
                missing_evidence.append(comment_id)
        elif classification in {"invalid", "not_applicable", "rejected"}:
            continue
        else:
            unresolved.append(comment_id)
    converged = (
        goals_satisfied
        and test_evidence_satisfied
        and not unresolved
        and not missing_evidence
        and not unresolved_route_issue
    )
    return {
        "review_converged": converged,
        "completion_allowed": converged,
        "unresolved_review_ids": unresolved,
        "missing_review_evidence_ids": missing_evidence,
        "optional_review_ids": optional,
        "unresolved_route_issue": unresolved_route_issue,
    }


def next_action(
    failure_class,
    attempt_count=1,
    *,
    threshold=DEFAULT_ATTEMPT_THRESHOLD,
    threshold_override=None,
    ledger=(),
    fingerprint=None,
    issue_id=None,
    review_comments=(),
    goals_satisfied=True,
    test_evidence_satisfied=True,
    unresolved_route_issue=False,
):
    """Return the bounded next step without selecting or invoking an entry."""

    if failure_class not in FAILURE_CLASSES:
        raise ValueError("unknown failure class: {}".format(failure_class))
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool) or attempt_count < 1:
        raise ValueError("attempt_count must be a positive integer")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ValueError("failure threshold must be a positive integer")
    if threshold_override is not None:
        override_report = validate_threshold_override(
            threshold_override,
            ledger,
            fingerprint=fingerprint,
            issue_id=issue_id,
        )
        if not override_report["valid"]:
            raise ValueError(override_report["conflicts"][0]["conflict"])
        threshold = override_report["threshold"]

    base = {
        "failure_class": failure_class,
        "attempt_count": attempt_count,
        "threshold": threshold,
        "will_auto_route": False,
        "selected_route": None,
        "requires_user_route_selection": False,
        "route_change_required": False,
    }
    if failure_class == "implementation_failure":
        if attempt_count == 1:
            action = "minimal_fix"
        elif attempt_count >= threshold:
            action = "recover_required"
        else:
            action = "root_cause_recheck"
        base.update(
            {
                "action": action,
                "ordinary_repair_allowed": action != "recover_required",
                "recommended_entry": (
                    "grh-recover" if action == "recover_required" else "grh-run"
                ),
            }
        )
    elif failure_class == "route_failure":
        base.update(
            {
                "action": "human_route_selection",
                "ordinary_repair_allowed": False,
                "recommended_entry": "grh-recover",
                "requires_user_route_selection": True,
                "route_change_required": True,
            }
        )
    elif failure_class == "evidence_failure":
        base.update(
            {
                "action": "more_evidence_required",
                "ordinary_repair_allowed": False,
                "recommended_entry": "grh-check",
            }
        )
    else:
        base.update(
            {
                "action": "reconcile_required",
                "ordinary_repair_allowed": False,
                "recommended_entry": "grh-recover",
            }
        )
    base.update(
        review_convergence(
            review_comments,
            goals_satisfied=goals_satisfied,
            test_evidence_satisfied=test_evidence_satisfied,
            unresolved_route_issue=(
                unresolved_route_issue or failure_class == "route_failure"
            ),
        )
    )
    return base


__all__ = [
    "DEFAULT_ATTEMPT_THRESHOLD",
    "FAILURE_CLASSES",
    "REPAIR_MODES",
    "issue_fingerprint",
    "next_action",
    "record_attempt",
    "review_convergence",
    "validate_threshold_override",
]
