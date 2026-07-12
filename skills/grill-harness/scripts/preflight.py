"""Read-only dependency preflight for Grill Harness."""

import json
import re
import subprocess
from pathlib import Path

import entry_contract


REQUIRED_CAPABILITIES = ("grilling", "domain-modeling", "codebase-design")
COMPATIBILITY_REFERENCES = ("grill-with-docs",)
PUBLIC_ENTRIES = tuple(entry_contract.PUBLIC_ENTRIES)
ENTRY_CORE_CONTRACT_VERSION = entry_contract.ENTRY_CORE_CONTRACT_VERSION


def _default_runner(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def _metadata_name(skill_file):
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    frontmatter = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", text, re.DOTALL)
    if not frontmatter:
        return None
    match = re.search(r"(?m)^name:\s*['\"]?([^'\"\n]+)", frontmatter.group(1))
    return match.group(1).strip() if match else None


def _metadata_contract_version(skill_file):
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    frontmatter = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", text, re.DOTALL)
    if not frontmatter:
        return None
    match = re.search(
        r"(?m)^entry_core_contract_version:\s*([0-9]+)\s*$",
        frontmatter.group(1),
    )
    return int(match.group(1)) if match else None


def _entries(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("skills", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _cli_inventory(runner):
    inventory = []
    errors = []
    failed_scopes = []
    successes = 0
    commands = (
        (["npx", "skills", "list", "--json"], "project"),
        (["npx", "skills", "list", "-g", "--json"], "global"),
    )
    for command, scope in commands:
        try:
            response = runner(command)
        except (FileNotFoundError, OSError) as error:
            errors.append("{}: {}".format(scope, error))
            failed_scopes.append(scope)
            continue
        if not response or response.get("returncode") != 0:
            errors.append(
                "{}: {}".format(
                    scope, (response or {}).get("stderr", "skills CLI failed")
                )
            )
            failed_scopes.append(scope)
            continue
        try:
            payload = json.loads(response.get("stdout", ""))
        except (TypeError, json.JSONDecodeError) as error:
            errors.append("{}: invalid CLI JSON: {}".format(scope, error))
            failed_scopes.append(scope)
            continue
        successes += 1
        for entry in _entries(payload):
            normalized = dict(entry)
            normalized["scope"] = scope
            inventory.append(normalized)
    return (
        successes == len(commands),
        inventory,
        "; ".join(errors) or None,
        tuple(failed_scopes),
    )


def _filesystem_inventory(roots):
    entries = []
    scoped_roots = roots if isinstance(roots, dict) else {"unknown": roots}
    for scope, paths in scoped_roots.items():
        for root in paths:
            root = Path(root)
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir(), key=lambda item: item.name):
                if child.is_dir() and (child / "SKILL.md").is_file():
                    entries.append({"name": child.name, "path": str(child), "scope": scope})
    return entries


def _verify(name, candidates):
    stale = False
    for entry in candidates:
        raw_path = entry.get("path") or entry.get("root")
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        skill_file = path / "SKILL.md"
        if not path.exists() or not skill_file.is_file():
            stale = True
            continue
        metadata_name = _metadata_name(skill_file)
        if metadata_name != name:
            stale = True
            continue
        return {
            "verified": True,
            "status": "available",
            "path": str(path),
            "resolved_path": str(path.resolve()),
            "symlink": path.is_symlink(),
            "scope": entry.get("scope", "unknown"),
            "metadata_name": metadata_name,
        }
    return {
        "verified": False,
        "status": "stale-metadata" if stale else "missing",
        "path": None,
        "resolved_path": None,
        "symlink": False,
        "scope": None,
        "metadata_name": None,
    }


def _core_contract(core_path):
    if not core_path:
        return None, False
    contract_path = Path(core_path) / "references" / "入口内核契约.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, False
    version = contract.get("contract_version")
    declared_entries = contract.get("entries")
    compatible = (
        version == ENTRY_CORE_CONTRACT_VERSION
        and isinstance(declared_entries, dict)
        and set(declared_entries) == set(PUBLIC_ENTRIES)
    )
    return version, compatible


def verify_public_entries(inventory, invoking_entry=None):
    """Verify the complete public entry set and its shared core contract."""

    if invoking_entry is not None and invoking_entry not in PUBLIC_ENTRIES:
        raise ValueError("unknown public entry: {}".format(invoking_entry))
    entries = []
    for name in PUBLIC_ENTRIES:
        candidates = [item for item in inventory if item.get("name") == name]
        result = _verify(name, candidates)
        result["name"] = name
        result["entry_contract_version"] = (
            _metadata_contract_version(Path(result["path"]) / "SKILL.md")
            if result["verified"] else None
        )
        entries.append(result)
    missing_entries = [item["name"] for item in entries if not item["verified"]]
    core = next(item for item in entries if item["name"] == "grill-harness")
    core_path = core["path"] if core["verified"] else None
    contract_version, contract_compatible = _core_contract(core_path)
    incompatible_entries = [
        item["name"] for item in entries
        if item["verified"]
        and item["entry_contract_version"] != ENTRY_CORE_CONTRACT_VERSION
    ]
    contract_compatible = contract_compatible and not incompatible_entries
    entry_ready = not missing_entries and contract_compatible
    return {
        "checked": True,
        "invoking_entry": invoking_entry,
        "entry_ready": entry_ready,
        "entries": entries,
        "missing_entries": missing_entries,
        "incompatible_entries": incompatible_entries,
        "core_path": core_path,
        "contract_version": contract_version,
        "expected_contract_version": ENTRY_CORE_CONTRACT_VERSION,
        "contract_compatible": contract_compatible,
        "actions_performed": False,
    }


def _safe_top_level_help(runner):
    try:
        response = runner(["npx", "skills", "--help"])
    except (FileNotFoundError, OSError):
        return None
    if not response or response.get("returncode") != 0:
        return None
    return response.get("stdout", "")


def _batch_command(help_text, capabilities):
    if not help_text or not capabilities:
        return None
    has_add_source = re.search(r"(?m)^\s*add\s+<(?:source|package)>(?=\s|$)", help_text)
    required_flags = ("--global", "--agent", "--skill", "--yes", "--copy")
    if not has_add_source or any(flag not in help_text for flag in required_flags):
        return None
    return (
        "npx skills add mattpocock/skills -g -a codex claude-code "
        "-s {} -y --copy"
    ).format(" ".join(capabilities))


def _update_command(help_text, capabilities):
    if not help_text or not capabilities:
        return None
    update_line = re.search(
        r"(?m)^\s*update\s+(?:\[(?:skills(?:\.\.\.)?)\]|<(?:skills(?:\.\.\.)?)>|skills(?:\.\.\.)?)(?=\s|$)",
        help_text,
    )
    if not update_line:
        return None
    return "npx skills update {} -g".format(" ".join(capabilities))


def run_preflight(
    skill_roots=(),
    runner=None,
    optional_capabilities=(),
    check_harness_entries=False,
    invoking_entry=None,
):
    """Discover, verify, and report capabilities without changing the system."""

    runner = _default_runner if runner is None else runner
    cli_complete, cli_entries, cli_error, failed_scopes = _cli_inventory(runner)
    cli_available = cli_complete or bool(cli_entries)
    inventory = list(cli_entries)
    if not cli_complete:
        fallback_roots = skill_roots
        if isinstance(skill_roots, dict) and failed_scopes:
            fallback_roots = {
                scope: skill_roots.get(scope, ())
                for scope in failed_scopes
            }
        inventory.extend(_filesystem_inventory(fallback_roots))
    names = list(REQUIRED_CAPABILITIES) + list(optional_capabilities) + list(COMPATIBILITY_REFERENCES)
    capabilities = []
    for name in names:
        candidates = [item for item in inventory if item.get("name") == name]
        result = _verify(name, candidates)
        required = name in REQUIRED_CAPABILITIES
        reference = name in COMPATIBILITY_REFERENCES
        result.update({
            "name": name,
            "required": required,
            "role": "compatibility-reference" if reference else ("required" if required else "optional"),
            "callable_dependency": not reference,
        })
        capabilities.append(result)

    missing_required = [item["name"] for item in capabilities if item["required"] and not item["verified"]]
    missing_optional = [item["name"] for item in capabilities if item["role"] == "optional" and not item["verified"]]
    if check_harness_entries:
        harness_installation = verify_public_entries(inventory, invoking_entry=invoking_entry)
    else:
        harness_installation = {
            "checked": False,
            "invoking_entry": invoking_entry,
            "entry_ready": True,
            "entries": [],
            "missing_entries": [],
            "incompatible_entries": [],
            "core_path": None,
            "contract_version": None,
            "expected_contract_version": ENTRY_CORE_CONTRACT_VERSION,
            "contract_compatible": None,
            "actions_performed": False,
        }
    entry_ready = harness_installation["entry_ready"]
    install_commands = []
    update_commands = []
    if cli_available:
        help_text = _safe_top_level_help(runner)
        command = _batch_command(help_text, missing_required)
        install_commands = [command] if command else []
        update = _update_command(help_text, REQUIRED_CAPABILITIES)
        update_commands = [update] if update else []
    return {
        "ready": not missing_required,
        "entry_ready": entry_ready,
        "overall_ready": not missing_required and entry_ready,
        "cli": {
            "available": cli_available,
            "complete": cli_complete,
            "error": cli_error,
            "inventory_source": "json-first",
        },
        "capabilities": capabilities,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "install_commands": install_commands,
        "update_commands": update_commands,
        "harness_installation": harness_installation,
        "actions_performed": False,
        "accepted_upstream_changes": False,
    }


__all__ = [
    "COMPATIBILITY_REFERENCES",
    "ENTRY_CORE_CONTRACT_VERSION",
    "PUBLIC_ENTRIES",
    "REQUIRED_CAPABILITIES",
    "run_preflight",
    "verify_public_entries",
]
