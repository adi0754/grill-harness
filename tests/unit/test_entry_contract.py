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


if __name__ == "__main__":
    unittest.main()
