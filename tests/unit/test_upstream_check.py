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

        change = next(item for item in report["changes"] if item["classification"] == "renamed-or-deleted")
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


if __name__ == "__main__":
    unittest.main()
