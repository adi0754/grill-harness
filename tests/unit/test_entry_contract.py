import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import entry_contract


class EntryContractTests(unittest.TestCase):
    def test_all_public_entries_share_the_entry_core_contract_version(self):
        expected = {
            "grill-harness",
            "grh-start",
            "grh-plan",
            "grh-run",
            "grh-check",
            "grh-recover",
            "grh-learn",
            "grh-upstream-check",
        }

        self.assertEqual(set(entry_contract.PUBLIC_ENTRIES), expected)
        contract = entry_contract.get_entry_contract()
        self.assertEqual(contract["contract_version"], entry_contract.ENTRY_CORE_CONTRACT_VERSION)
        self.assertTrue(
            all(
                item["contract_version"] == entry_contract.ENTRY_CORE_CONTRACT_VERSION
                for item in contract["entries"].values()
            )
        )

    def test_every_entry_declares_the_complete_permission_contract(self):
        required_fields = {
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
        for name, contract in entry_contract.PUBLIC_ENTRIES.items():
            with self.subTest(entry=name):
                self.assertTrue(required_fields.issubset(contract))

    def test_requested_scope_can_only_narrow_entry_permissions(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-check",
            {"status": "active", "gates": {}},
            {"valid": True, "conflicts": []},
            requested_scope=("review", "switch_route", "install", "final_acceptance"),
        )

        self.assertEqual(decision["allowed_scope"], ["review", "final_acceptance"])
        self.assertIn("switch_route", decision["forbidden_scope"])
        self.assertIn("install", decision["forbidden_scope"])
        self.assertFalse(decision["will_auto_route"])

    def test_run_requires_final_spec_approval(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-run",
            {"status": "active", "gates": {"final_spec_approval": {"status": "awaiting_user"}}},
            {"valid": True, "conflicts": []},
        )

        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason_code"], "missing_prerequisites")
        self.assertIn("final_spec_approval", decision["missing_prerequisites"])
        self.assertEqual(decision["recommended_entry"], "grh-plan")
        self.assertFalse(decision["will_auto_route"])

    def test_check_cannot_switch_routes(self):
        contract = entry_contract.PUBLIC_ENTRIES["grh-check"]

        self.assertNotIn("switch_route", contract["allowed_operations"])
        self.assertIn("switch_route", contract["forbidden_operations"])

    def test_upstream_check_cannot_install_or_update(self):
        contract = entry_contract.PUBLIC_ENTRIES["grh-upstream-check"]

        self.assertTrue(contract["supports_read_only"])
        self.assertFalse(contract["may_write_runtime"])
        self.assertTrue({"install", "update"}.issubset(contract["forbidden_operations"]))

    def test_every_decision_is_human_routed(self):
        for name in entry_contract.PUBLIC_ENTRIES:
            with self.subTest(entry=name):
                decision = entry_contract.evaluate_entry_request(
                    name,
                    {"status": "not_started", "gates": {}},
                    {"valid": True, "conflicts": []},
                )
                self.assertFalse(decision["will_auto_route"])

    def test_entry_is_blocked_when_current_and_next_phases_are_outside_its_contract(self):
        approved = {
            "final_spec_approval": {
                "status": "approved",
                "approval_id": "DEC-003",
                "artifact_versions": {"specification": 1},
            }
        }
        cases = (
            ("grh-run", "specification", "specification", "grh-plan"),
            ("grh-start", "implementation", "implementation", "grh-run"),
        )
        for entry, current, next_phase, recommended in cases:
            with self.subTest(entry=entry):
                decision = entry_contract.evaluate_entry_request(
                    entry,
                    {
                        "status": "active",
                        "current_phase": current,
                        "next_eligible_phase": next_phase,
                        "gates": approved,
                    },
                    {"valid": True, "conflicts": []},
                )
                self.assertFalse(decision["eligible"])
                self.assertEqual(decision["reason_code"], "phase_not_allowed")
                self.assertEqual(decision["recommended_entry"], recommended)

    def test_learn_keeps_search_and_retrospective_but_restricts_unapproved_archive(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-learn",
            {
                "status": "active",
                "current_phase": "implementation",
                "next_eligible_phase": "implementation",
                "gates": {},
                "phases": [{"id": "independent_assurance", "status": "pending"}],
                "evidence": [],
            },
            {"valid": True, "conflicts": []},
        )

        self.assertTrue(decision["eligible"])
        self.assertEqual(decision["reason_code"], "eligible_with_restricted_scope")
        self.assertEqual(decision["allowed_scope"], ["search_knowledge", "retrospective"])
        self.assertIn("archive_knowledge", decision["forbidden_scope"])
        self.assertEqual(
            decision["missing_prerequisites"],
            ["independent_assurance_completed", "current_acceptance_passed", "archive_confirmed"],
        )

    def test_learn_allows_formal_archive_only_after_acceptance_and_confirmation(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-learn",
            {
                "status": "active",
                "git_baseline": "current-commit",
                "current_phase": "knowledge_archive",
                "next_eligible_phase": "knowledge_archive",
                "gates": {},
                "phases": [{"id": "independent_assurance", "status": "completed"}],
                "evidence": [{
                    "id": "EVD-001",
                    "kind": "final_acceptance",
                    "status": "completed",
                    "result": "accepted",
                    "current": True,
                    "baseline": "current-commit",
                }],
                "archive_confirmation": {"status": "approved"},
            },
            {"valid": True, "conflicts": []},
            requested_scope=("archive_knowledge",),
        )

        self.assertTrue(decision["eligible"])
        self.assertEqual(decision["allowed_scope"], ["archive_knowledge"])
        self.assertEqual(decision["missing_prerequisites"], [])


if __name__ == "__main__":
    unittest.main()
