"""Pure, human-controlled entry permission and eligibility policy."""

import copy
import json
from pathlib import Path


ENTRY_CORE_CONTRACT_VERSION = 1
_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "references" / "入口内核契约.json"
_REQUIRED_FIELDS = {
    "kind",
    "allowed_phases",
    "required_gates",
    "allowed_operations",
    "forbidden_operations",
    "stop_boundary",
    "next_entry_suggestions",
    "supports_read_only",
    "may_initialize",
    "may_write_runtime",
    "may_write_product",
    "may_archive_knowledge",
}


def _load_contract():
    with _CONTRACT_PATH.open(encoding="utf-8") as source:
        contract = json.load(source)
    if contract.get("contract_version") != ENTRY_CORE_CONTRACT_VERSION:
        raise ValueError("entry-core contract version mismatch")
    entries = contract.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("entry-core contract must declare entries")
    for name, entry in entries.items():
        if not isinstance(entry, dict) or not _REQUIRED_FIELDS.issubset(entry):
            raise ValueError("entry-core contract is malformed for {}".format(name))
        entry["contract_version"] = ENTRY_CORE_CONTRACT_VERSION
    return contract


_CONTRACT = _load_contract()
PUBLIC_ENTRIES = _CONTRACT["entries"]


def get_entry_contract():
    """Return an isolated copy so callers cannot mutate the shared policy."""

    return copy.deepcopy(_CONTRACT)


def _gate_is_approved(gate):
    return (
        isinstance(gate, dict)
        and gate.get("status") == "approved"
        and isinstance(gate.get("approval_id"), str)
        and bool(gate["approval_id"].strip())
        and isinstance(gate.get("artifact_versions"), dict)
        and bool(gate["artifact_versions"])
    )


def evaluate_entry_request(entry_name, workflow, reconciliation, requested_scope=()):
    """Evaluate an entry request without reading or changing external state."""

    if entry_name not in PUBLIC_ENTRIES:
        raise ValueError("unknown public entry: {}".format(entry_name))
    if not isinstance(workflow, dict) or not isinstance(reconciliation, dict):
        raise ValueError("workflow and reconciliation must be mappings")
    if isinstance(requested_scope, str):
        requested_scope = (requested_scope,)
    if not isinstance(requested_scope, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in requested_scope
    ):
        raise ValueError("requested scope must contain non-empty strings")

    contract = PUBLIC_ENTRIES[entry_name]
    allowed_operations = list(contract["allowed_operations"])
    requested = list(dict.fromkeys(item.strip() for item in requested_scope))
    allowed_scope = (
        [item for item in requested if item in allowed_operations]
        if requested
        else allowed_operations
    )
    forbidden_scope = list(contract["forbidden_operations"])
    forbidden_scope.extend(
        item for item in requested if item not in allowed_operations and item not in forbidden_scope
    )

    status = workflow.get("status")
    gates = workflow.get("gates", {})
    if not isinstance(gates, dict):
        raise ValueError("workflow gates must be a mapping")
    missing = [
        gate for gate in contract["required_gates"]
        if not _gate_is_approved(gates.get(gate))
    ]
    eligible = True
    reason_code = "eligible"
    recommended_entry = None
    if not reconciliation.get("valid", False):
        eligible = entry_name in {"grill-harness", "grh-recover"}
        if not eligible:
            reason_code = "reconciliation_required"
            recommended_entry = "grh-recover"
    elif status == "not_started" and entry_name not in {
        "grill-harness", "grh-start", "grh-upstream-check"
    }:
        eligible = False
        reason_code = "workflow_not_started"
        recommended_entry = "grh-start"
    elif missing:
        eligible = False
        reason_code = "missing_prerequisites"
        recommended_entry = "grh-plan" if "final_spec_approval" in missing else "grh-start"

    return {
        "entry": entry_name,
        "eligible": eligible,
        "reason_code": reason_code,
        "missing_prerequisites": missing,
        "allowed_scope": allowed_scope,
        "forbidden_scope": forbidden_scope,
        "recommended_entry": recommended_entry,
        "will_auto_route": False,
    }


def entry_control_summary(entry_name, workflow, decision):
    """Build the stable, read-only control summary shown before an entry runs."""

    if entry_name not in PUBLIC_ENTRIES or not isinstance(workflow, dict):
        raise ValueError("invalid entry control summary input")
    contract = PUBLIC_ENTRIES[entry_name]
    return {
        "contract_version": ENTRY_CORE_CONTRACT_VERSION,
        "entry": entry_name,
        "workflow_status": workflow.get("status"),
        "current_phase": workflow.get("current_phase"),
        "allowed_scope": list(decision["allowed_scope"]),
        "forbidden_scope": list(decision["forbidden_scope"]),
        "stop_boundary": contract["stop_boundary"],
        "missing_prerequisites": list(decision["missing_prerequisites"]),
        "recommended_entry": decision["recommended_entry"],
        "will_auto_route": False,
    }


__all__ = [
    "ENTRY_CORE_CONTRACT_VERSION",
    "PUBLIC_ENTRIES",
    "entry_control_summary",
    "evaluate_entry_request",
    "get_entry_contract",
]
