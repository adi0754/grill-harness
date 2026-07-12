"""Pinned upstream manifests and read-only compatibility checks.

The adapter never installs, updates, or accepts an upstream Skill.  Remote
inspection is performed against an isolated temporary Git checkout.
"""

import copy
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FIELDS = (
    "schema_version",
    "repository",
    "ref",
    "commit",
    "checked_at",
    "upstream_updated_at",
    "upstream_release",
    "license",
    "license_path",
    "copyright",
    "hash_algorithm",
    "tracked_capabilities",
    "source_paths",
    "source_urls",
    "hashes",
    "reference_files",
    "behavior_contracts",
    "design_inputs",
    "local_differences",
    "local_extension_points",
    "risks",
    "last_test_results",
)


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _source_url(repository, commit, path):
    canonical = repository[:-4] if repository.endswith(".git") else repository
    if canonical.startswith("https://github.com/"):
        return "{}/blob/{}/{}".format(canonical, commit, path)
    return "{}@{}:{}".format(repository, commit, path)


def _invalid(errors):
    raise ValueError("invalid upstream manifest: {}".format(", ".join(sorted(set(errors)))))


def validate_manifest(manifest):
    """Validate a pinned manifest completely, failing closed on old/corrupt data."""

    if not isinstance(manifest, dict):
        _invalid(["root must be a mapping"])
    errors = []
    expected_fields = set(MANIFEST_FIELDS)
    actual_fields = set(manifest)
    for field in sorted(expected_fields - actual_fields):
        errors.append("missing {}".format(field))
    for field in sorted(actual_fields - expected_fields):
        errors.append("unknown {}".format(field))
    if errors:
        _invalid(errors)

    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    for field in (
        "repository",
        "ref",
        "commit",
        "checked_at",
        "upstream_updated_at",
        "upstream_release",
        "license",
        "license_path",
        "copyright",
        "hash_algorithm",
    ):
        if not _nonempty_string(manifest.get(field)):
            errors.append("{} must be a non-empty string".format(field))
    if manifest.get("hash_algorithm") != "sha256":
        errors.append("hash_algorithm must be sha256")

    tracked = manifest.get("tracked_capabilities")
    if not isinstance(tracked, list) or not tracked or not all(_nonempty_string(item) for item in tracked):
        errors.append("tracked_capabilities must be a non-empty string list")
        tracked_set = set()
    elif len(tracked) != len(set(tracked)):
        errors.append("tracked_capabilities must be unique")
        tracked_set = set(tracked)
    else:
        tracked_set = set(tracked)

    source_paths = manifest.get("source_paths")
    source_urls = manifest.get("source_urls")
    contracts = manifest.get("behavior_contracts")
    reference_files = manifest.get("reference_files")
    hashes = manifest.get("hashes")
    for field, value in (
        ("source_paths", source_paths),
        ("source_urls", source_urls),
        ("behavior_contracts", contracts),
        ("reference_files", reference_files),
        ("hashes", hashes),
    ):
        if not isinstance(value, dict):
            errors.append("{} must be a mapping".format(field))

    if isinstance(source_paths, dict):
        if not all(_nonempty_string(key) and _nonempty_string(value) for key, value in source_paths.items()):
            errors.append("source_paths entries must be non-empty strings")
        if not set(source_paths).issubset(tracked_set):
            errors.append("source_paths contains untracked capabilities")
    if isinstance(source_urls, dict) and isinstance(source_paths, dict):
        if set(source_urls) != set(source_paths):
            errors.append("source_urls must cover source_paths exactly")
        if not all(_nonempty_string(value) for value in source_urls.values()):
            errors.append("source_urls entries must be non-empty strings")
    if isinstance(contracts, dict):
        if set(contracts) != tracked_set:
            errors.append("behavior_contracts must cover tracked_capabilities exactly")
        if not all(isinstance(value, dict) and value for value in contracts.values()):
            errors.append("behavior_contracts entries must be non-empty mappings")
        reference = contracts.get("grill-with-docs")
        if reference is not None and (
            reference.get("role") != "compatibility-reference"
            or reference.get("callable_dependency") is not False
        ):
            errors.append("grill-with-docs must remain a non-callable compatibility reference")
    if isinstance(reference_files, dict):
        if not all(_nonempty_string(path) and _nonempty_string(digest)
                   for path, digest in reference_files.items()):
            errors.append("reference_files entries must be non-empty strings")
    if isinstance(hashes, dict) and isinstance(source_paths, dict) and isinstance(reference_files, dict):
        expected_hash_paths = set(source_paths.values()) | set(reference_files)
        if set(hashes) != expected_hash_paths:
            errors.append("hashes must cover tracked source and reference files exactly")
        if not all(_nonempty_string(value) for value in hashes.values()):
            errors.append("hashes entries must be non-empty strings")

    for field in ("design_inputs", "local_differences", "local_extension_points"):
        value = manifest.get(field)
        if not isinstance(value, list) or not value or not all(_nonempty_string(item) for item in value):
            errors.append("{} must be a non-empty string list".format(field))
    risks = manifest.get("risks")
    if not isinstance(risks, list) or not all(_nonempty_string(item) for item in risks):
        errors.append("risks must be a string list")
    results = manifest.get("last_test_results")
    if not isinstance(results, dict) or not results:
        errors.append("last_test_results must be a non-empty mapping")

    if errors:
        _invalid(errors)
    return manifest


def build_manifest(facts, checked_at):
    """Construct and validate a schema-v1 manifest from observed upstream facts."""

    if not isinstance(facts, dict):
        raise ValueError("incomplete upstream facts: root must be a mapping")
    required_scalars = (
        "repository",
        "ref",
        "commit",
        "upstream_updated_at",
        "upstream_release",
        "license",
        "license_path",
        "copyright",
        "hash_algorithm",
    )
    missing = [field for field in required_scalars if not _nonempty_string(facts.get(field))]
    if not _nonempty_string(checked_at):
        missing.append("checked_at")
    sources = facts.get("sources")
    contracts_source = facts.get("behavior_contracts")
    if not isinstance(sources, dict) or not sources:
        missing.append("sources")
        sources = {}
    if not isinstance(contracts_source, dict) or not contracts_source:
        missing.append("behavior_contracts")
        contracts_source = {}
    for capability, source in sources.items():
        if not isinstance(source, dict) or not source.get("path") or not source.get("hash"):
            missing.append("sources.{}".format(capability))
    tracked = facts.get("tracked_capabilities", sorted(set(sources) | set(contracts_source)))
    if not isinstance(tracked, list) or not tracked:
        missing.append("tracked_capabilities")
        tracked = []
    for capability in tracked:
        if not isinstance(contracts_source.get(capability), dict) or not contracts_source.get(capability):
            missing.append("behavior_contracts.{}".format(capability))
    reference_files = facts.get("reference_files")
    if not isinstance(reference_files, dict):
        missing.append("reference_files")
        reference_files = {}
    for field in ("design_inputs", "local_differences", "local_extension_points"):
        value = facts.get(field)
        if not isinstance(value, list) or not value:
            missing.append(field)
    risks = facts.get("risks")
    if not isinstance(risks, list):
        missing.append("risks")
    results = facts.get("last_test_results")
    if not isinstance(results, dict) or not results:
        missing.append("last_test_results")
    if missing:
        raise ValueError("incomplete upstream facts: {}".format(", ".join(sorted(set(missing)))))

    contracts = copy.deepcopy(contracts_source)
    reference = contracts.setdefault("grill-with-docs", {})
    reference["role"] = "compatibility-reference"
    reference["callable_dependency"] = False
    source_paths = {name: item["path"] for name, item in sorted(sources.items())}
    source_hashes = {item["path"]: item["hash"] for item in sources.values()}
    all_hashes = dict(reference_files)
    all_hashes.update(source_hashes)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "repository": facts["repository"],
        "ref": facts["ref"],
        "commit": facts["commit"],
        "checked_at": checked_at,
        "upstream_updated_at": facts["upstream_updated_at"],
        "upstream_release": facts["upstream_release"],
        "license": facts["license"],
        "license_path": facts["license_path"],
        "copyright": facts["copyright"],
        "hash_algorithm": facts["hash_algorithm"],
        "tracked_capabilities": sorted(tracked),
        "source_paths": source_paths,
        "source_urls": {
            name: _source_url(facts["repository"], facts["commit"], path)
            for name, path in source_paths.items()
        },
        "hashes": dict(sorted(all_hashes.items())),
        "reference_files": dict(sorted(reference_files.items())),
        "behavior_contracts": contracts,
        "design_inputs": copy.deepcopy(facts["design_inputs"]),
        "local_differences": copy.deepcopy(facts["local_differences"]),
        "local_extension_points": copy.deepcopy(facts["local_extension_points"]),
        "risks": copy.deepcopy(facts["risks"]),
        "last_test_results": copy.deepcopy(facts["last_test_results"]),
    }
    return validate_manifest(manifest)


def _frontmatter(source):
    if not source.startswith("---"):
        return {}
    parts = source.split("---", 2)
    if len(parts) < 3:
        return {}
    fields = {}
    for line in parts[1].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if not match:
            continue
        value = match.group(2).strip().strip("\"'")
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        fields[match.group(1)] = value
    return fields


def _observe_contract(contract, content, frontmatter):
    observed = copy.deepcopy(contract)
    observed.pop("observations", None)
    markers = observed.get("required_markers", [])
    expected_frontmatter = observed.get("frontmatter_expectations", {})
    observed["observations"] = {
        "source_present": content is not None,
        "required_markers_present": {
            marker: content is not None and marker in content for marker in markers
        },
        "frontmatter": {
            key: frontmatter.get(key) for key in sorted(expected_frontmatter)
        },
    }
    return observed


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(runner, command, cwd=None, timeout=30):
    return runner(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def _reason(error):
    detail = getattr(error, "stderr", None) or str(error)
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    return " ".join(str(detail).strip().split()) or type(error).__name__


def _normalize_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_remote_facts(manifest, runner=subprocess.run, timeout=30):
    """Read an upstream Git ref in a temporary checkout.

    Returns ``status=unavailable`` for transport/tool failures.  A successful
    result contains raw facts suitable for :func:`build_manifest`.
    """

    validate_manifest(manifest)
    try:
        with tempfile.TemporaryDirectory(prefix="grh-upstream-") as temp_dir:
            checkout = Path(temp_dir) / "checkout"
            _run(
                runner,
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--depth",
                    "1",
                    "--no-tags",
                    "--branch",
                    manifest["ref"],
                    manifest["repository"],
                    str(checkout),
                ],
                timeout=timeout,
            )
            commit = _run(
                runner, ["git", "rev-parse", "HEAD"], cwd=str(checkout), timeout=timeout
            ).stdout.strip()
            updated_at = _normalize_timestamp(_run(
                runner,
                ["git", "show", "-s", "--format=%cI", "HEAD"],
                cwd=str(checkout),
                timeout=timeout,
            ).stdout.strip())

            candidates = {}
            candidate_contents = {}
            for path in checkout.rglob("SKILL.md"):
                relative = path.relative_to(checkout).as_posix()
                content = path.read_text(encoding="utf-8")
                name = _frontmatter(content).get("name")
                if _nonempty_string(name):
                    candidates[name] = relative
                    candidate_contents[name] = content

            sources = {}
            contracts = {}
            for capability in manifest["tracked_capabilities"]:
                expected = manifest["source_paths"].get(capability)
                expected_path = checkout / expected if expected else None
                if expected_path is not None and expected_path.is_file():
                    content = expected_path.read_text(encoding="utf-8")
                    metadata = _frontmatter(content)
                    path = expected
                else:
                    path = candidates.get(capability)
                    content = candidate_contents.get(capability)
                    metadata = _frontmatter(content) if content is not None else {}
                if path is not None:
                    sources[capability] = {
                        "path": path,
                        "hash": _sha256(checkout / path),
                    }
                contracts[capability] = _observe_contract(
                    manifest["behavior_contracts"][capability], content, metadata
                )

            references = {}
            for relative in manifest["reference_files"]:
                path = checkout / relative
                references[relative] = _sha256(path) if path.is_file() else "missing"

            license_path = checkout / manifest["license_path"]
            license_text = (
                license_path.read_text(encoding="utf-8", errors="replace")
                if license_path.is_file()
                else ""
            )
            references[manifest["license_path"]] = (
                _sha256(license_path) if license_path.is_file() else "missing"
            )
            copyright_match = re.search(r"Copyright[^\r\n]+", license_text, re.IGNORECASE)
            package_path = checkout / "package.json"
            release = manifest["upstream_release"]
            if package_path.is_file():
                package = json.loads(package_path.read_text(encoding="utf-8"))
                if _nonempty_string(package.get("version")):
                    release = package["version"]
            license_name = "MIT" if "MIT License" in license_text else manifest["license"]
            facts = {
                "repository": manifest["repository"],
                "ref": manifest["ref"],
                "commit": commit,
                "upstream_updated_at": updated_at,
                "upstream_release": release,
                "license": license_name,
                "license_path": manifest["license_path"],
                "copyright": (
                    copyright_match.group(0) if copyright_match else manifest["copyright"]
                ),
                "hash_algorithm": "sha256",
                "tracked_capabilities": copy.deepcopy(manifest["tracked_capabilities"]),
                "sources": sources,
                "reference_files": references,
                "behavior_contracts": contracts,
                "design_inputs": copy.deepcopy(manifest["design_inputs"]),
                "local_differences": copy.deepcopy(manifest["local_differences"]),
                "local_extension_points": copy.deepcopy(manifest["local_extension_points"]),
                "risks": copy.deepcopy(manifest["risks"]),
                "last_test_results": {
                    "status": "not-run",
                    "reason": "remote facts observed; compatibility tests not run",
                },
            }
    except (OSError, subprocess.SubprocessError, TimeoutError, json.JSONDecodeError) as error:
        return {
            "status": "unavailable",
            "reason": _reason(error),
            "actions_performed": False,
            "accepted_upstream_changes": False,
        }
    return {
        "status": "available",
        "facts": facts,
        "actions_performed": False,
        "accepted_upstream_changes": False,
    }


def _change(classification, **details):
    return dict({"classification": classification}, **details)


def _compare(previous, current):
    changes = []
    previous_paths = previous["source_paths"]
    current_paths = current["source_paths"]
    previous_contracts = previous["behavior_contracts"]
    current_contracts = current["behavior_contracts"]
    capabilities = sorted(set(previous["tracked_capabilities"]) | set(current["tracked_capabilities"]))
    for capability in capabilities:
        old_path = previous_paths.get(capability)
        new_path = current_paths.get(capability)
        if old_path is None and new_path is not None:
            changes.append(_change("added", capability=capability, new_path=new_path, risk="medium"))
        elif old_path is not None and new_path is None:
            changes.append(_change("removed", capability=capability, old_path=old_path, risk="high"))
        elif old_path != new_path:
            changes.append(_change("renamed", capability=capability, old_path=old_path,
                                   new_path=new_path, risk="high"))
        old_contract = previous_contracts.get(capability)
        new_contract = current_contracts.get(capability)
        if old_contract is not None and new_contract is not None and old_contract != new_contract:
            changes.append(_change("behavior-contract-change", capability=capability,
                                   path=new_path, risk="high"))
        if old_path and new_path:
            old_hash = previous["hashes"].get(old_path)
            new_hash = current["hashes"].get(new_path)
            if old_hash != new_hash:
                classification = (
                    "content-fix"
                    if old_path == new_path and old_contract == new_contract
                    else "content-change"
                )
                changes.append(_change(classification, capability=capability,
                                       old_path=old_path, new_path=new_path, risk="medium"))

    for path in sorted(set(previous["reference_files"]) | set(current["reference_files"])):
        old_hash = previous["reference_files"].get(path)
        new_hash = current["reference_files"].get(path)
        if old_hash is None:
            changes.append(_change("reference-added", path=path, risk="low"))
        elif new_hash is None or new_hash == "missing":
            changes.append(_change("reference-removed", path=path, risk="high"))
        elif old_hash != new_hash:
            classification = "license-change" if path == previous["license_path"] else "reference-content-change"
            changes.append(_change(classification, path=path, risk="high" if classification == "license-change" else "medium"))

    metadata_fields = (
        "repository", "ref", "commit", "upstream_release", "license",
        "license_path", "copyright", "upstream_updated_at",
    )
    changed_metadata = [field for field in metadata_fields if previous[field] != current[field]]
    if changed_metadata:
        changes.append(_change("metadata-change", fields=changed_metadata, risk="low"))
    return changes


def _recommend(changes):
    classifications = {item["classification"] for item in changes}
    if "behavior-contract-change" in classifications:
        return "暂缓更新"
    if classifications & {"removed", "renamed", "reference-removed", "license-change"}:
        return "人工决策"
    if classifications & {
        "content-fix", "content-change", "reference-content-change",
        "reference-added", "metadata-change", "added",
    }:
        return "更新依赖"
    return "无需处理"


def check_upstream(previous_manifest, local_facts, offline=False, remote_loader=None, checked_at=None):
    """Compare pinned facts and return a report; never accept or apply changes."""

    validate_manifest(previous_manifest)
    remote_reason = None
    if offline:
        current = build_manifest(local_facts, checked_at)
        mode = "offline"
    else:
        remote = None
        if remote_loader is not None:
            try:
                remote = remote_loader()
            except (OSError, subprocess.SubprocessError, TimeoutError) as error:
                remote = {"status": "unavailable", "reason": _reason(error)}
        if remote is None:
            mode = "unavailable"
            current = copy.deepcopy(previous_manifest)
        elif isinstance(remote, dict) and remote.get("status") == "unavailable":
            mode = "unavailable"
            remote_reason = remote.get("reason")
            current = copy.deepcopy(previous_manifest)
        else:
            facts = remote.get("facts") if isinstance(remote, dict) and remote.get("status") == "available" else remote
            current = build_manifest(facts, checked_at)
            mode = "online"
    changes = _compare(previous_manifest, current) if mode != "unavailable" else []
    compatibility_tests = (
        current.get("last_test_results", {})
        if changes
        else previous_manifest.get("last_test_results", {})
    )
    recommendation = _recommend(changes)
    if (
        changes
        and recommendation == "更新依赖"
        and compatibility_tests.get("status") != "passed"
    ):
        recommendation = "暂缓更新"
    report = {
        "mode": mode,
        "previous_commit": previous_manifest["commit"],
        "observed_commit": current["commit"],
        "observed_manifest": current,
        "changes": changes,
        "recommendation": recommendation,
        "compatibility_tests": compatibility_tests,
        "actions_performed": False,
        "accepted_upstream_changes": False,
    }
    if remote_reason:
        report["remote_reason"] = remote_reason
    return report


__all__ = [
    "MANIFEST_FIELDS",
    "MANIFEST_SCHEMA_VERSION",
    "build_manifest",
    "check_upstream",
    "load_remote_facts",
    "validate_manifest",
]
