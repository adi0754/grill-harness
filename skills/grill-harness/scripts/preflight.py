"""Read-only dependency preflight for Grill Harness."""

import json
import re
import subprocess
from pathlib import Path


REQUIRED_CAPABILITIES = ("grilling", "domain-modeling", "codebase-design")
COMPATIBILITY_REFERENCES = ("grill-with-docs",)


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
    commands = (
        (["npx", "skills", "list", "--json"], "project"),
        (["npx", "skills", "list", "-g", "--json"], "global"),
    )
    for command, scope in commands:
        try:
            response = runner(command)
        except (FileNotFoundError, OSError) as error:
            return False, [], str(error)
        if not response or response.get("returncode") != 0:
            return False, [], (response or {}).get("stderr", "skills CLI failed")
        try:
            payload = json.loads(response.get("stdout", ""))
        except (TypeError, json.JSONDecodeError) as error:
            return False, [], "invalid CLI JSON: {}".format(error)
        for entry in _entries(payload):
            normalized = dict(entry)
            normalized["scope"] = scope
            inventory.append(normalized)
    return True, inventory, None


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
    if "add <source>" not in help_text or "--skill" not in help_text:
        return None
    return "npx skills add mattpocock/skills --skill {}".format(" ".join(capabilities))


def _update_command(help_text, capabilities):
    if not help_text or not capabilities or "update <skills...>" not in help_text:
        return None
    return "npx skills update {} -g".format(" ".join(capabilities))


def run_preflight(skill_roots=(), runner=None, optional_capabilities=()):
    """Discover, verify, and report capabilities without changing the system."""

    runner = _default_runner if runner is None else runner
    cli_available, cli_entries, cli_error = _cli_inventory(runner)
    inventory = cli_entries if cli_available else _filesystem_inventory(skill_roots)
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
        "cli": {"available": cli_available, "error": cli_error, "inventory_source": "json-first"},
        "capabilities": capabilities,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "install_commands": install_commands,
        "update_commands": update_commands,
        "actions_performed": False,
        "accepted_upstream_changes": False,
    }


__all__ = ["COMPATIBILITY_REFERENCES", "REQUIRED_CAPABILITIES", "run_preflight"]
