import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "skills" / "grill-harness" / "scripts"
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "workflows"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate


def load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class ArtifactContractTests(unittest.TestCase):
    def test_valid_workflow_reconciles_without_conflicts(self):
        workflow = load_fixture("valid_workflow.json")
        report = validate.reconcile_workflow(workflow)

        self.assertTrue(report["valid"])
        self.assertEqual(report["conflicts"], [])

    def test_reconciliation_reports_conflict_and_recovery_in_chinese_without_repairing(self):
        workflow = load_fixture("contradictory_workflow.json")
        before = copy.deepcopy(workflow)

        report = validate.reconcile_workflow(workflow)

        self.assertFalse(report["valid"])
        self.assertGreaterEqual(len(report["conflicts"]), 2)
        for conflict in report["conflicts"]:
            self.assertTrue(conflict["conflict"])
            self.assertTrue(conflict["recovery_action"])
            self.assertRegex(conflict["conflict"] + conflict["recovery_action"], "[\u4e00-\u9fff]")
        self.assertEqual(workflow, before)

    def test_changed_decision_marks_affected_specs_tasks_and_evidence_stale(self):
        workflow = load_fixture("changed_decision.json")
        workflow["tasks"][0].pop("decisions")
        workflow["tasks"][0]["depends_on"] = ["spec-v1"]
        workflow["evidence"][0].pop("decisions")
        workflow["evidence"][0]["depends_on"] = ["TASK-001"]
        original = copy.deepcopy(workflow)

        updated = validate.propagate_decision_change(workflow, "DEC-001")

        self.assertEqual(workflow, original)
        self.assertEqual(updated["artifacts"][0]["status"], "stale")
        self.assertEqual(updated["tasks"][0]["status"], "stale")
        self.assertEqual(updated["evidence"][0]["status"], "stale")
        self.assertEqual(updated["artifacts"][1]["status"], "completed")
        self.assertEqual(updated["tasks"][1]["status"], "pending")
        self.assertEqual(updated["evidence"][1]["status"], "valid")
        for affected in (updated["artifacts"][0], updated["tasks"][0], updated["evidence"][0]):
            self.assertEqual(affected["stale_because"], "DEC-001")
            self.assertEqual(affected["currentness"], "stale")

    def test_changed_decision_marks_terminal_dependents_noncurrent_without_erasing_lifecycle(self):
        workflow = {
            "artifacts": [
                {"id": "spec", "status": "superseded", "decisions": ["DEC-001"]}
            ],
            "tasks": [
                {"id": "TASK-001", "status": "failed", "decisions": ["DEC-001"]},
                {"id": "TASK-002", "status": "cancelled", "depends_on": ["spec"]},
            ],
            "evidence": [
                {"id": "EVD-001", "status": "valid", "depends_on": ["TASK-001"]}
            ],
        }

        updated = validate.propagate_decision_change(workflow, "DEC-001")

        for collection, expected_statuses in (
            ("artifacts", ["superseded"]),
            ("tasks", ["failed", "cancelled"]),
            ("evidence", ["stale"]),
        ):
            self.assertEqual(
                [record["status"] for record in updated[collection]],
                expected_statuses,
            )
            self.assertTrue(
                all(record["currentness"] == "stale" for record in updated[collection])
            )

    def test_reconciliation_reports_duplicate_ids_instead_of_overwriting_them(self):
        workflow = load_fixture("valid_workflow.json")
        workflow["artifacts"].append(
            {"id": "spec-v1", "kind": "spec", "status": "stale"}
        )

        report = validate.reconcile_workflow(workflow)

        self.assertFalse(report["valid"])
        self.assertIn("DUPLICATE_ID", {item["code"] for item in report["conflicts"]})

    def test_superseded_artifact_propagates_staleness_to_direct_dependents(self):
        workflow = load_fixture("valid_workflow.json")
        updated = validate.propagate_superseded(workflow, "spec-v1")

        self.assertEqual(updated["artifacts"][0]["status"], "superseded")
        self.assertEqual(updated["tasks"][0]["status"], "stale")
        self.assertEqual(updated["evidence"][0]["status"], "stale")

    def test_mutation_entries_reject_duplicate_ids_with_chinese_recovery_guidance(self):
        workflow = load_fixture("valid_workflow.json")
        workflow["artifacts"].append(
            {"id": "spec-v1", "kind": "spec", "status": "completed"}
        )

        for mutate in (
            lambda: validate.propagate_superseded(workflow, "spec-v1"),
            lambda: validate.propagate_decision_change(workflow, "DEC-001"),
        ):
            with self.subTest(mutate=mutate):
                with self.assertRaisesRegex(ValueError, "重复 ID.*确认.*替代关系"):
                    mutate()


if __name__ == "__main__":
    unittest.main()
