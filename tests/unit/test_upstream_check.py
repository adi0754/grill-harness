import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "skills" / "grill-harness" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "upstream"
sys.path.insert(0, str(SCRIPTS_DIR))

import upstream_check


class UpstreamCheckTests(unittest.TestCase):
    def _fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_manifest_contains_every_pinned_audit_field(self):
        facts = self._fixture("current.json")

        manifest = upstream_check.build_manifest(facts, checked_at="2026-07-12T00:00:00Z")

        self.assertEqual(set(manifest), {
            "repository", "ref", "commit", "checked_at", "upstream_updated_at",
            "license", "source_paths", "hashes", "behavior_contracts",
            "local_differences", "risks", "last_test_results",
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

        report = upstream_check.check_upstream(
            previous, local_facts=self._fixture("renamed.json"), offline=True,
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

        report = upstream_check.check_upstream(
            previous, local_facts=self._fixture("metadata_and_fix.json"), offline=True,
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
