"""Pinned upstream manifest construction and read-only compatibility checks."""

import copy


MANIFEST_FIELDS = (
    "repository", "ref", "commit", "checked_at", "upstream_updated_at", "license",
    "source_paths", "hashes", "behavior_contracts", "local_differences", "risks",
    "last_test_results",
)


def build_manifest(facts, checked_at):
    required_scalars = ("repository", "ref", "commit", "license")
    missing = [field for field in required_scalars if not facts.get(field)]
    if not checked_at:
        missing.append("checked_at")
    sources = facts.get("sources", {})
    contracts_source = facts.get("behavior_contracts", {})
    if not isinstance(sources, dict) or not sources:
        missing.append("sources")
    if not isinstance(contracts_source, dict) or not contracts_source:
        missing.append("behavior_contracts")
    for capability, source in sources.items():
        if not isinstance(source, dict) or not source.get("path") or not source.get("hash"):
            missing.append("sources.{}".format(capability))
        if not contracts_source.get(capability):
            missing.append("behavior_contracts.{}".format(capability))
    for field in ("local_differences", "risks", "last_test_results"):
        if field not in facts or facts.get(field) is None:
            missing.append(field)
    if not facts.get("last_test_results"):
        missing.append("last_test_results")
    if missing:
        raise ValueError("incomplete upstream facts: {}".format(", ".join(sorted(set(missing)))))
    contracts = copy.deepcopy(contracts_source)
    reference = contracts.setdefault("grill-with-docs", {})
    reference["role"] = "compatibility-reference"
    reference["callable_dependency"] = False
    return {
        "repository": facts.get("repository"),
        "ref": facts.get("ref"),
        "commit": facts.get("commit"),
        "checked_at": checked_at,
        "upstream_updated_at": facts.get("upstream_updated_at"),
        "license": facts.get("license"),
        "source_paths": {name: item.get("path") for name, item in sorted(sources.items())},
        "hashes": {item.get("path"): item.get("hash") for item in sources.values() if item.get("path")},
        "behavior_contracts": contracts,
        "local_differences": copy.deepcopy(facts.get("local_differences", [])),
        "risks": copy.deepcopy(facts.get("risks", [])),
        "last_test_results": copy.deepcopy(facts.get("last_test_results", {})),
    }


def _change(classification, **details):
    return dict({"classification": classification}, **details)


def _compare(previous, current):
    changes = []
    previous_paths = previous.get("source_paths", {})
    current_paths = current.get("source_paths", {})
    previous_contracts = previous.get("behavior_contracts", {})
    current_contracts = current.get("behavior_contracts", {})
    capabilities = sorted(set(previous_paths) | set(current_paths))
    for capability in capabilities:
        old_path = previous_paths.get(capability)
        new_path = current_paths.get(capability)
        if old_path is None:
            changes.append(_change("added", capability=capability, new_path=new_path, risk="medium"))
        elif new_path is None:
            changes.append(_change("removed", capability=capability, old_path=old_path, risk="high"))
        elif old_path != new_path:
            changes.append(_change("renamed", capability=capability, old_path=old_path, new_path=new_path, risk="high"))
        old_contract = previous_contracts.get(capability)
        new_contract = current_contracts.get(capability)
        if old_contract is not None and new_contract is not None and old_contract != new_contract:
            changes.append(_change("behavior-contract-change", capability=capability, path=new_path, risk="high"))
        if old_path and new_path:
            old_hash = previous.get("hashes", {}).get(old_path)
            new_hash = current.get("hashes", {}).get(new_path)
            if old_hash != new_hash:
                classification = "content-fix" if old_path == new_path and old_contract == new_contract else "content-change"
                changes.append(_change(classification, capability=capability, old_path=old_path, new_path=new_path, risk="medium"))

    metadata_fields = ("repository", "ref", "commit", "license", "upstream_updated_at")
    changed_metadata = [field for field in metadata_fields if previous.get(field) != current.get(field)]
    if changed_metadata:
        changes.append(_change("metadata-change", fields=changed_metadata, risk="low"))
    return changes


def _recommend(changes):
    classifications = {item["classification"] for item in changes}
    if "behavior-contract-change" in classifications:
        return "暂缓更新"
    if classifications & {"removed", "renamed"}:
        return "人工决策"
    if classifications & {"content-fix", "metadata-change"}:
        return "更新依赖"
    return "无需处理"


def check_upstream(previous_manifest, local_facts, offline=False, remote_loader=None, checked_at=None):
    """Compare pinned facts and return a report; never accept or apply changes."""

    facts = local_facts
    mode = "offline" if offline else "unavailable"
    if not offline and remote_loader is not None:
        remote_facts = remote_loader()
        if remote_facts is not None:
            facts = remote_facts
            mode = "online"
    current = build_manifest(facts, checked_at)
    changes = _compare(previous_manifest, current)
    return {
        "mode": mode,
        "previous_commit": previous_manifest.get("commit"),
        "observed_commit": current.get("commit"),
        "observed_manifest": current,
        "changes": changes,
        "recommendation": _recommend(changes),
        "actions_performed": False,
        "accepted_upstream_changes": False,
    }


__all__ = ["MANIFEST_FIELDS", "build_manifest", "check_upstream"]
