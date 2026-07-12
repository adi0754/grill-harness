import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "skills" / "grill-harness" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "upstream"
PRODUCTION_MANIFEST = ROOT / "skills" / "grill-harness" / "references" / "上游清单.yaml"
sys.path.insert(0, str(SCRIPTS_DIR))

import upstream_check


class UpstreamCheckTests(unittest.TestCase):
    def _fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_manifest_contains_every_pinned_audit_field(self):
        facts = self._fixture("current.json")

        manifest = upstream_check.build_manifest(facts, checked_at="2026-07-12T00:00:00Z")

        self.assertEqual(set(manifest), {
            "schema_version", "repository", "ref", "commit", "checked_at",
            "upstream_updated_at", "upstream_release", "license",
            "license_path", "copyright", "hash_algorithm",
            "tracked_capabilities", "source_paths", "source_urls", "hashes",
            "reference_files", "behavior_contracts", "design_inputs",
            "local_differences", "local_extension_points", "risks",
            "last_test_results",
        })
        self.assertEqual(manifest["commit"], "abc123")
        self.assertEqual(manifest["hashes"]["skills/grilling/SKILL.md"], "hash-grilling-v1")

    def test_manifest_rejects_missing_or_incomplete_audit_facts(self):
        required_failures = (
            {},
            dict(self._fixture("current.json"), repository=""),
            dict(self._fixture("current.json"), upstream_updated_at=None),
            dict(self._fixture("current.json"), sources={"grilling": {"path": "x"}}),
            dict(self._fixture("current.json"), behavior_contracts={}),
            dict(self._fixture("current.json"), reference_files=None),
            dict(self._fixture("current.json"), design_inputs=[]),
            dict(self._fixture("current.json"), local_extension_points=[]),
            dict(self._fixture("current.json"), last_test_results={}),
        )

        for facts in required_failures:
            with self.subTest(facts=facts):
                with self.assertRaises(ValueError):
                    upstream_check.build_manifest(facts, checked_at="2026-07-12T00:00:00Z")

        missing_timestamp = self._fixture("current.json")
        del missing_timestamp["upstream_updated_at"]
        with self.assertRaises(ValueError):
            upstream_check.build_manifest(missing_timestamp, checked_at="2026-07-12T00:00:00Z")

    def test_previous_manifest_is_validated_before_remote_access(self):
        previous = upstream_check.build_manifest(
            self._fixture("current.json"), "2026-07-11T00:00:00Z"
        )
        previous.pop("reference_files")
        calls = []

        with self.assertRaisesRegex(ValueError, "invalid upstream manifest"):
            upstream_check.check_upstream(
                previous,
                local_facts=self._fixture("current.json"),
                remote_loader=lambda: calls.append("remote"),
                checked_at="2026-07-12T00:00:00Z",
            )

        self.assertEqual(calls, [])

    def test_corrupt_previous_manifest_fails_closed(self):
        corruptions = (
            ("source_paths", []),
            ("tracked_capabilities", "grilling"),
            ("hashes", {"untracked": "hash"}),
            ("behavior_contracts", {"grilling": {}}),
            ("actions_performed", True),
        )

        for field, value in corruptions:
            with self.subTest(field=field):
                previous = upstream_check.build_manifest(
                    self._fixture("current.json"), "2026-07-11T00:00:00Z"
                )
                previous[field] = value
                with self.assertRaisesRegex(ValueError, "invalid upstream manifest"):
                    upstream_check.validate_manifest(previous)

    def test_offline_mode_compares_local_facts_without_remote_or_mutation(self):
        previous = upstream_check.build_manifest(self._fixture("current.json"), "2026-07-11T00:00:00Z")
        calls = []

        report = upstream_check.check_upstream(
            previous, local_facts=self._fixture("current.json"), offline=True,
            remote_loader=lambda: calls.append("remote"), checked_at="2026-07-12T00:00:00Z"
        )

        self.assertEqual(calls, [])
        self.assertEqual(report["mode"], "offline")
        self.assertEqual(report["recommendation"], "无需处理")
        self.assertFalse(report["actions_performed"])
        self.assertFalse(report["accepted_upstream_changes"])

    def test_renamed_upstream_file_is_classified_without_accepting_it(self):
        previous = upstream_check.build_manifest(self._fixture("current.json"), "2026-07-11T00:00:00Z")
        renamed = self._fixture("renamed.json")
        renamed["behavior_contracts"]["grilling"] = self._fixture("current.json")[
            "behavior_contracts"
        ]["grilling"]

        report = upstream_check.check_upstream(
            previous, local_facts=renamed, offline=True,
            checked_at="2026-07-12T00:00:00Z"
        )

        change = next(item for item in report["changes"] if item["classification"] == "renamed")
        self.assertEqual(change["old_path"], "skills/grilling/SKILL.md")
        self.assertEqual(change["new_path"], "skills/grill/SKILL.md")
        self.assertEqual(report["recommendation"], "人工决策")
        self.assertFalse(report["accepted_upstream_changes"])

    def test_behavior_contract_change_is_high_risk_even_when_path_is_stable(self):
        previous = upstream_check.build_manifest(self._fixture("current.json"), "2026-07-11T00:00:00Z")

        report = upstream_check.check_upstream(
            previous, local_facts=self._fixture("behavior_changed.json"), offline=True,
            checked_at="2026-07-12T00:00:00Z"
        )

        change = next(item for item in report["changes"] if item["classification"] == "behavior-contract-change")
        self.assertEqual(change["capability"], "grilling")
        self.assertEqual(change["risk"], "high")
        self.assertEqual(report["recommendation"], "暂缓更新")

    def test_metadata_only_change_and_content_fix_are_distinguished(self):
        previous = upstream_check.build_manifest(self._fixture("current.json"), "2026-07-11T00:00:00Z")
        changed = self._fixture("metadata_and_fix.json")
        changed["behavior_contracts"]["grilling"] = self._fixture("current.json")[
            "behavior_contracts"
        ]["grilling"]

        report = upstream_check.check_upstream(
            previous, local_facts=changed, offline=True,
            checked_at="2026-07-12T00:00:00Z"
        )

        classifications = {item["classification"] for item in report["changes"]}
        self.assertIn("metadata-change", classifications)
        self.assertIn("content-fix", classifications)
        self.assertEqual(report["recommendation"], "更新依赖")

    def test_grill_with_docs_is_recorded_only_as_a_reference(self):
        manifest = upstream_check.build_manifest(self._fixture("current.json"), "2026-07-12T00:00:00Z")

        contract = manifest["behavior_contracts"]["grill-with-docs"]
        self.assertEqual(contract["role"], "compatibility-reference")
        self.assertFalse(contract["callable_dependency"])

    def test_missing_remote_facts_downgrades_online_check_to_unavailable(self):
        previous = upstream_check.build_manifest(self._fixture("current.json"), "2026-07-11T00:00:00Z")

        report = upstream_check.check_upstream(
            previous, local_facts=self._fixture("current.json"), offline=False,
            remote_loader=lambda: None, checked_at="2026-07-12T00:00:00Z"
        )

        self.assertEqual(report["mode"], "unavailable")
        self.assertFalse(report["actions_performed"])
        self.assertFalse(report["accepted_upstream_changes"])

    def test_remote_loader_reports_unavailable_without_mutating_anything(self):
        previous = upstream_check.build_manifest(
            self._fixture("current.json"), "2026-07-11T00:00:00Z"
        )
        commands = []

        def unavailable_runner(command, **kwargs):
            commands.append(command)
            raise subprocess.CalledProcessError(128, command, stderr="network down")

        result = upstream_check.load_remote_facts(previous, runner=unavailable_runner)

        self.assertEqual(result["status"], "unavailable")
        self.assertIn("network down", result["reason"])
        self.assertFalse(result["actions_performed"])
        self.assertFalse(result["accepted_upstream_changes"])
        flattened = " ".join(" ".join(command) for command in commands)
        self.assertNotIn("skills add", flattened)
        self.assertNotIn("skills update", flattened)

    @unittest.skipUnless(shutil.which("git"), "git is required for the read-only loader test")
    def test_remote_loader_reads_a_git_snapshot_and_detects_contract_change(self):
        previous = upstream_check.build_manifest(
            self._fixture("current.json"), "2026-07-11T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir) / "remote"
            repository.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.email", "test@example.com"],
                           cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
            for capability, path in previous["source_paths"].items():
                if capability == "grilling":
                    path = "skills/moved/grilling/SKILL.md"
                skill = repository / path
                skill.parent.mkdir(parents=True, exist_ok=True)
                body = "---\nname: {}\n---\n{}\n".format(
                    capability,
                    "changed behavior" if capability == "grilling" else capability,
                )
                skill.write_text(body, encoding="utf-8")
            for path in previous["reference_files"]:
                reference = repository / path
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text("reference\n", encoding="utf-8")
            (repository / "LICENSE").write_text("MIT License\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-m", "fixture"], cwd=repository, check=True,
                           stdout=subprocess.DEVNULL)
            previous["repository"] = str(repository)

            result = upstream_check.load_remote_facts(previous)

        self.assertEqual(result["status"], "available")
        self.assertFalse(result["actions_performed"])
        facts = result["facts"]
        self.assertEqual(facts["ref"], "main")
        self.assertEqual(
            facts["sources"]["grilling"]["path"],
            "skills/moved/grilling/SKILL.md",
        )
        observations = facts["behavior_contracts"]["grilling"]["observations"]
        self.assertFalse(all(observations["required_markers_present"].values()))

    def test_check_accepts_structured_unavailable_remote_result(self):
        previous = upstream_check.build_manifest(
            self._fixture("current.json"), "2026-07-11T00:00:00Z"
        )

        report = upstream_check.check_upstream(
            previous,
            local_facts=self._fixture("current.json"),
            remote_loader=lambda: {
                "status": "unavailable",
                "reason": "DNS failure",
                "actions_performed": False,
                "accepted_upstream_changes": False,
            },
            checked_at="2026-07-12T00:00:00Z",
        )

        self.assertEqual(report["mode"], "unavailable")
        self.assertEqual(report["remote_reason"], "DNS failure")
        self.assertEqual(report["observed_commit"], previous["commit"])
        self.assertFalse(report["actions_performed"])

    def test_production_manifest_pins_real_upstream_sources_and_license(self):
        manifest = json.loads(PRODUCTION_MANIFEST.read_text(encoding="utf-8"))

        upstream_check.validate_manifest(manifest)

        self.assertEqual(manifest["repository"], "https://github.com/mattpocock/skills.git")
        self.assertEqual(manifest["ref"], "main")
        self.assertEqual(
            manifest["commit"], "391a2701dd948f94f56a39f7533f8eea9a859c87"
        )
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["license_path"], "LICENSE")
        self.assertIn("2026 Matt Pocock", manifest["copyright"])
        self.assertEqual(
            manifest["source_paths"],
            {
                "codebase-design": "skills/engineering/codebase-design/SKILL.md",
                "domain-modeling": "skills/engineering/domain-modeling/SKILL.md",
                "grill-with-docs": "skills/engineering/grill-with-docs/SKILL.md",
                "grilling": "skills/productivity/grilling/SKILL.md",
            },
        )
        self.assertFalse(
            manifest["behavior_contracts"]["grill-with-docs"]["callable_dependency"]
        )

    def test_added_removed_renamed_hash_contract_and_commit_changes_are_all_reported(self):
        previous = upstream_check.build_manifest(self._fixture("current.json"), "2026-07-11T00:00:00Z")
        changed = self._fixture("behavior_changed.json")
        changed["sources"]["grilling"]["path"] = "skills/grill/SKILL.md"
        changed["sources"].pop("domain-modeling")
        changed["behavior_contracts"].pop("domain-modeling")
        changed["sources"]["new-capability"] = {"path": "skills/new/SKILL.md", "hash": "new-hash"}
        changed["behavior_contracts"]["new-capability"] = {"summary": "new behavior"}

        report = upstream_check.check_upstream(
            previous, local_facts=changed, offline=True, checked_at="2026-07-12T00:00:00Z"
        )

        classifications = [item["classification"] for item in report["changes"]]
        self.assertIn("added", classifications)
        self.assertIn("removed", classifications)
        self.assertIn("renamed", classifications)
        self.assertIn("content-change", classifications)
        self.assertIn("behavior-contract-change", classifications)
        metadata = next(item for item in report["changes"] if item["classification"] == "metadata-change")
        self.assertIn("commit", metadata["fields"])


if __name__ == "__main__":
    unittest.main()
