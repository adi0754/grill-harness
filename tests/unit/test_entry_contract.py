import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import entry_contract


class EntryContractTests(unittest.TestCase):
    def test_thin_entries_document_explicit_workflow_selection(self):
        repo_root = Path(__file__).resolve().parents[2]
        guidance = (
            "项目存在多个工作流时必须显式传 `--workflow`，先用 "
            "`status`/`overview` 列出候选并让用户选择，不得替用户猜测。"
        )
        for entry in (
            "grh-start",
            "grh-plan",
            "grh-run",
            "grh-check",
            "grh-recover",
            "grh-learn",
        ):
            with self.subTest(entry=entry):
                text = (repo_root / "skills" / entry / "SKILL.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn(
                    "--project <项目绝对路径> "
                    "[--workflow <工作流或state.yaml绝对路径>]",
                    text,
                )
                self.assertIn(guidance, text)

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

    def test_unknown_only_requested_scope_fails_closed(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-check",
            {
                "status": "active",
                "current_phase": "independent_assurance",
                "next_eligible_phase": "independent_assurance",
                "gates": {
                    "final_spec_approval": {
                        "status": "approved",
                        "approval_id": "DEC-003",
                        "artifact_versions": {"ART-SPEC": 1},
                    }
                },
            },
            {"valid": True, "conflicts": []},
            requested_scope=("只完成仓库挑战，不修改产品代码",),
        )

        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason_code"], "requested_scope_not_allowed")
        self.assertEqual(decision["allowed_scope"], [])
        self.assertEqual(decision["unknown_scope"], ["只完成仓库挑战，不修改产品代码"])
        self.assertIsNone(decision["recommended_entry"])

        blocked = entry_contract.evaluate_entry_request(
            "grh-check",
            {
                "status": "active",
                "current_phase": "independent_assurance",
                "next_eligible_phase": "independent_assurance",
                "gates": {},
            },
            {"valid": True, "conflicts": []},
            requested_scope=("只完成仓库挑战，不修改产品代码",),
        )
        self.assertEqual(blocked["reason_code"], "missing_prerequisites")
        self.assertEqual(blocked["recommended_entry"], "grh-plan")

    def test_mixed_known_and_unknown_requested_scope_keeps_known_permissions(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-check",
            {
                "status": "active",
                "current_phase": "independent_assurance",
                "next_eligible_phase": "independent_assurance",
                "gates": {
                    "final_spec_approval": {
                        "status": "approved",
                        "approval_id": "DEC-003",
                        "artifact_versions": {"ART-SPEC": 1},
                    }
                },
            },
            {"valid": True, "conflicts": []},
            requested_scope=("review", "不改代码"),
        )

        self.assertTrue(decision["eligible"])
        self.assertEqual(decision["reason_code"], "eligible")
        self.assertEqual(decision["allowed_scope"], ["review"])
        self.assertEqual(decision["unknown_scope"], ["不改代码"])

    def test_empty_requested_scope_keeps_all_allowed_operations(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-check",
            {
                "status": "active",
                "current_phase": "independent_assurance",
                "next_eligible_phase": "independent_assurance",
                "gates": {
                    "final_spec_approval": {
                        "status": "approved",
                        "approval_id": "DEC-003",
                        "artifact_versions": {"ART-SPEC": 1},
                    }
                },
            },
            {"valid": True, "conflicts": []},
        )

        self.assertTrue(decision["eligible"])
        self.assertEqual(
            decision["allowed_scope"],
            entry_contract.PUBLIC_ENTRIES["grh-check"]["allowed_operations"],
        )
        self.assertEqual(decision["unknown_scope"], [])

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

    def test_design_phase_block_recommends_start_without_a_plan_hop(self):
        decision = entry_contract.evaluate_entry_request(
            "grh-run",
            {
                "status": "active",
                "current_phase": "design",
                "next_eligible_phase": "design",
                "gates": {
                    "requirements_baseline": {
                        "status": "approved",
                        "approval_id": "DEC-001",
                        "artifact_versions": {"ART-BASELINE": 1},
                    },
                    "final_spec_approval": {
                        "status": "approved",
                        "approval_id": "DEC-003",
                        "artifact_versions": {"ART-SPEC": 1},
                    },
                },
            },
            {"valid": True, "conflicts": []},
        )

        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason_code"], "phase_not_allowed")
        self.assertEqual(decision["recommended_entry"], "grh-start")

    def test_start_owns_design_until_the_user_selects_a_route(self):
        workflow = {
            "status": "active",
            "current_phase": "design",
            "next_eligible_phase": "design",
            "gates": {
                "requirements_baseline": {
                    "status": "approved",
                    "approval_id": "DEC-001",
                    "artifact_versions": {"ART-BASELINE": 1},
                }
            },
        }
        reconciliation = {"valid": True, "conflicts": []}

        start = entry_contract.evaluate_entry_request(
            "grh-start", workflow, reconciliation
        )
        plan = entry_contract.evaluate_entry_request(
            "grh-plan", workflow, reconciliation
        )
        self.assertTrue(start["eligible"])
        self.assertEqual(start["reason_code"], "eligible")
        self.assertFalse(plan["eligible"])
        self.assertEqual(plan["missing_prerequisites"], ["route_selection"])
        self.assertEqual(plan["recommended_entry"], "grh-start")

    def test_start_can_research_and_prototype_during_design(self):
        contract = entry_contract.PUBLIC_ENTRIES["grh-start"]
        self.assertTrue(
            {"research", "prototype"}.issubset(contract["allowed_operations"])
        )

        decision = entry_contract.evaluate_entry_request(
            "grh-start",
            {
                "status": "active",
                "current_phase": "design",
                "next_eligible_phase": "design",
                "gates": {
                    "requirements_baseline": {
                        "status": "approved",
                        "approval_id": "DEC-001",
                        "artifact_versions": {"ART-BASELINE": 1},
                    }
                },
            },
            {"valid": True, "conflicts": []},
            requested_scope=("research",),
        )

        self.assertTrue(decision["eligible"])
        self.assertEqual(decision["allowed_scope"], ["research"])

    def test_recover_is_eligible_in_every_machine_phase(self):
        phases = (
            "preflight",
            "alignment",
            "requirements_baseline",
            "design",
            "route_selection",
            "repository_challenge",
            "specification",
            "final_spec_approval",
            "tasking",
            "implementation",
            "independent_assurance",
            "knowledge_archive",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                decision = entry_contract.evaluate_entry_request(
                    "grh-recover",
                    {
                        "status": "active",
                        "current_phase": phase,
                        "next_eligible_phase": phase,
                        "gates": {},
                    },
                    {"valid": True, "conflicts": []},
                )

                self.assertTrue(decision["eligible"])
                self.assertEqual(decision["reason_code"], "eligible")

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
