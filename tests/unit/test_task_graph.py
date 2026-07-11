import copy
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import task_graph


class TaskGraphTests(unittest.TestCase):
    def test_acyclic_graph_has_a_deterministic_topological_order(self):
        tasks = [
            {"id": "TASK-003", "status": "pending", "depends_on": ["TASK-002"]},
            {"id": "TASK-001", "status": "completed", "depends_on": []},
            {"id": "TASK-002", "status": "pending", "depends_on": ["TASK-001"]},
        ]

        report = task_graph.validate_dag(tasks)

        self.assertTrue(report["valid"])
        self.assertEqual(report["topological_order"], ["TASK-001", "TASK-002", "TASK-003"])
        self.assertEqual(report["conflicts"], [])

    def test_cycle_is_reported_with_machine_code_and_chinese_recovery(self):
        tasks = [
            {"id": "TASK-001", "status": "pending", "depends_on": ["TASK-002"]},
            {"id": "TASK-002", "status": "pending", "depends_on": ["TASK-001"]},
        ]
        before = copy.deepcopy(tasks)

        report = task_graph.validate_dag(tasks)

        self.assertFalse(report["valid"])
        self.assertEqual(report["conflicts"][0]["code"], "TASK_GRAPH_CYCLE")
        self.assertEqual(report["conflicts"][0]["task_ids"], ["TASK-001", "TASK-002"])
        self.assertRegex(
            report["conflicts"][0]["conflict"]
            + report["conflicts"][0]["recovery_action"],
            "[\u4e00-\u9fff]",
        )
        self.assertEqual(tasks, before)

    def test_frontier_changes_only_when_all_blockers_are_completed(self):
        tasks = [
            {"id": "TASK-003", "status": "pending", "depends_on": ["TASK-002"]},
            {"id": "TASK-001", "status": "pending", "depends_on": []},
            {"id": "TASK-002", "status": "pending", "depends_on": ["TASK-001"]},
        ]

        self.assertEqual(task_graph.calculate_frontier(tasks)["frontier"], ["TASK-001"])
        tasks[1]["status"] = "completed"
        tasks[1]["currentness"] = "current"
        self.assertEqual(task_graph.calculate_frontier(tasks)["frontier"], ["TASK-002"])
        tasks[2]["status"] = "completed"
        tasks[2]["currentness"] = "current"
        self.assertEqual(task_graph.calculate_frontier(tasks)["frontier"], ["TASK-003"])

    def test_blocked_and_stale_dependencies_keep_tasks_out_of_frontier(self):
        tasks = [
            {"id": "TASK-001", "status": "blocked", "depends_on": []},
            {"id": "TASK-002", "status": "pending", "depends_on": ["TASK-001"]},
            {"id": "TASK-003", "status": "stale", "depends_on": []},
            {"id": "TASK-004", "status": "pending", "depends_on": ["TASK-003"]},
        ]

        report = task_graph.calculate_frontier(tasks)

        self.assertEqual(report["frontier"], [])
        blockers = {item["task_id"]: item["blockers"] for item in report["blocked"]}
        self.assertEqual(blockers["TASK-002"], ["TASK-001"])
        self.assertEqual(blockers["TASK-004"], ["TASK-003"])

    def test_blockers_alias_is_supported_and_cannot_contradict_depends_on(self):
        tasks = [
            {
                "id": "TASK-001",
                "status": "completed",
                "currentness": "current",
                "blockers": [],
            },
            {"id": "TASK-002", "status": "pending", "blockers": ["TASK-001"]},
        ]

        self.assertEqual(task_graph.calculate_frontier(tasks)["frontier"], ["TASK-002"])

        contradictory = [
            {"id": "TASK-001", "status": "completed", "depends_on": []},
            {
                "id": "TASK-002",
                "status": "pending",
                "depends_on": ["TASK-001"],
                "blockers": [],
            },
        ]
        report = task_graph.validate_dag(contradictory)
        self.assertFalse(report["valid"])
        self.assertIn(
            "CONTRADICTORY_BLOCKERS",
            {item["code"] for item in report["conflicts"]},
        )

    def test_frontier_requires_current_tasks_and_current_completed_dependencies(self):
        tasks = [
            {
                "id": "TASK-001",
                "status": "completed",
                "currentness": "unknown",
                "depends_on": [],
            },
            {
                "id": "TASK-002",
                "status": "pending",
                "currentness": "current",
                "depends_on": ["TASK-001"],
            },
            {
                "id": "TASK-003",
                "status": "pending",
                "currentness": "stale",
                "depends_on": [],
            },
        ]

        report = task_graph.calculate_frontier(tasks)

        self.assertEqual(report["frontier"], [])
        self.assertEqual(report["blocked"], [{"task_id": "TASK-002", "blockers": ["TASK-001"]}])

    def test_unknown_dependencies_and_duplicate_ids_fail_closed(self):
        cases = (
            [
                {"id": "TASK-001", "status": "pending", "depends_on": ["TASK-404"]},
            ],
            [
                {"id": "TASK-001", "status": "pending", "depends_on": []},
                {"id": "TASK-001", "status": "completed", "depends_on": []},
            ],
        )

        for tasks in cases:
            with self.subTest(tasks=tasks):
                report = task_graph.validate_dag(tasks)
                self.assertFalse(report["valid"])
                self.assertEqual(task_graph.calculate_frontier(tasks)["frontier"], [])
                self.assertRegex(
                    "".join(
                        item["conflict"] + item["recovery_action"]
                        for item in report["conflicts"]
                    ),
                    "[\u4e00-\u9fff]",
                )

    def test_task_without_explicit_dependency_field_is_malformed(self):
        tasks = [{"id": "TASK-001", "status": "pending"}]

        graph_report = task_graph.validate_dag(tasks)
        frontier_report = task_graph.calculate_frontier(tasks)
        parallel_report = task_graph.parallel_candidates(tasks)

        self.assertFalse(graph_report["valid"])
        self.assertIn(
            "MISSING_BLOCKERS",
            {item["code"] for item in graph_report["conflicts"]},
        )
        self.assertEqual(frontier_report["frontier"], [])
        self.assertFalse(parallel_report["valid"])

    def test_explicit_null_dependency_fields_are_invalid_not_empty_roots(self):
        for field in ("depends_on", "blockers"):
            with self.subTest(field=field):
                report = task_graph.validate_dag(
                    [{"id": "TASK-001", "status": "pending", field: None}]
                )

                self.assertFalse(report["valid"])
                self.assertIn(
                    "INVALID_BLOCKERS",
                    {item["code"] for item in report["conflicts"]},
                )


if __name__ == "__main__":
    unittest.main()
