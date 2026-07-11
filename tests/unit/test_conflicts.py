import copy
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import task_graph


def task(task_id, **changes):
    record = {
        "id": task_id,
        "status": "pending",
        "depends_on": [],
        "write_paths": [],
        "shared_contracts": [],
        "migrations": [],
        "generated_files": [],
        "worktree": "/worktrees/{}".format(task_id.lower()),
        "branch": "feature/{}".format(task_id.lower()),
    }
    record.update(changes)
    return record


class ParallelConflictTests(unittest.TestCase):
    def assert_conflict_code(self, left, right, code):
        report = task_graph.analyze_task_conflict(left, right)
        self.assertFalse(report["parallel_candidate"])
        self.assertFalse(report["executable_parallel"])
        self.assertIn(code, {item["code"] for item in report["conflicts"]})
        self.assertTrue(
            all(item["conflict"] and item["recovery_action"] for item in report["conflicts"])
        )
        self.assertRegex(
            "".join(
                item["conflict"] + item["recovery_action"]
                for item in report["conflicts"]
            ),
            "[\u4e00-\u9fff]",
        )

    def test_same_or_nested_write_paths_conflict(self):
        for left_path, right_path in (
            ("src/api.py", "src/api.py"),
            ("src/generated", "src/generated/client.py"),
        ):
            with self.subTest(left_path=left_path, right_path=right_path):
                self.assert_conflict_code(
                    task("TASK-001", write_paths=[left_path]),
                    task("TASK-002", write_paths=[right_path]),
                    "SHARED_WRITE_PATH",
                )

    def test_shared_contract_migration_and_generated_output_conflict(self):
        cases = (
            (
                task("TASK-001", shared_contracts=["UserSchema"]),
                task("TASK-002", shared_contracts=["UserSchema"]),
                "SHARED_CONTRACT",
            ),
            (
                task("TASK-001", migrations=["users-v2"]),
                task("TASK-002", migrations=["users-v2"]),
                "SHARED_MIGRATION",
            ),
            (
                task("TASK-001", generated_files=["src/client.py"]),
                task("TASK-002", generated_files=["src/client.py"]),
                "SHARED_GENERATED_FILE",
            ),
        )

        for left, right, code in cases:
            with self.subTest(code=code):
                self.assert_conflict_code(left, right, code)

    def test_distinct_worktrees_and_branches_make_independent_tasks_executable(self):
        left = task("TASK-001", write_paths=["src/a.py"])
        right = task("TASK-002", write_paths=["src/b.py"])
        before = copy.deepcopy((left, right))

        report = task_graph.analyze_task_conflict(left, right)

        self.assertTrue(report["parallel_candidate"])
        self.assertTrue(report["executable_parallel"])
        self.assertEqual(report["conflicts"], [])
        self.assertEqual((left, right), before)

    def test_candidate_without_distinct_worktrees_cannot_execute_in_parallel(self):
        left = task("TASK-001", write_paths=["src/a.py"], worktree="/repo")
        right = task("TASK-002", write_paths=["src/b.py"], worktree="/repo")

        report = task_graph.analyze_task_conflict(left, right)

        self.assertTrue(report["parallel_candidate"])
        self.assertFalse(report["executable_parallel"])
        self.assertEqual(report["conflicts"][0]["code"], "WORKTREE_NOT_DISTINCT")

    def test_candidate_without_distinct_branches_cannot_execute_in_parallel(self):
        left = task("TASK-001", write_paths=["src/a.py"], branch="feature/shared")
        right = task("TASK-002", write_paths=["src/b.py"], branch="feature/shared")

        report = task_graph.analyze_task_conflict(left, right)

        self.assertTrue(report["parallel_candidate"])
        self.assertFalse(report["executable_parallel"])
        self.assertEqual(report["conflicts"][0]["code"], "BRANCH_NOT_DISTINCT")

    def test_invalid_conflict_metadata_fails_closed(self):
        for field in ("write_paths", "shared_contracts", "migrations", "generated_files"):
            with self.subTest(field=field):
                left = task("TASK-001", **{field: "src/shared.py"})
                right = task("TASK-002", **{field: ["src/shared.py"]})

                report = task_graph.analyze_task_conflict(left, right)

                self.assertFalse(report["parallel_candidate"])
                self.assertFalse(report["executable_parallel"])
                self.assertIn(
                    "INVALID_CONFLICT_FIELD",
                    {item["code"] for item in report["conflicts"]},
                )

    def test_missing_conflict_metadata_fails_closed(self):
        for field in ("write_paths", "shared_contracts", "migrations", "generated_files"):
            with self.subTest(field=field):
                left = task("TASK-001")
                del left[field]

                report = task_graph.analyze_task_conflict(left, task("TASK-002"))

                self.assertFalse(report["parallel_candidate"])
                self.assertFalse(report["executable_parallel"])
                self.assertIn(
                    "INVALID_CONFLICT_FIELD",
                    {item["code"] for item in report["conflicts"]},
                )

    def test_parallel_candidates_only_include_frontier_pairs_without_conflicts(self):
        tasks = [
            task("TASK-003", depends_on=["TASK-001"], write_paths=["src/c.py"]),
            task("TASK-002", write_paths=["src/b.py"]),
            task("TASK-001", write_paths=["src/a.py"]),
        ]

        report = task_graph.parallel_candidates(tasks)

        self.assertTrue(report["valid"])
        self.assertEqual(report["frontier"], ["TASK-001", "TASK-002"])
        self.assertEqual(
            [(item["task_ids"], item["executable_parallel"]) for item in report["candidates"]],
            [(["TASK-001", "TASK-002"], True)],
        )

    def test_parallel_candidates_rejects_logical_pair_without_execution_isolation(self):
        tasks = [
            task("TASK-001", write_paths=["src/a.py"], worktree="/repo"),
            task("TASK-002", write_paths=["src/b.py"], worktree="/repo"),
        ]

        report = task_graph.parallel_candidates(tasks)

        self.assertEqual(report["candidates"], [])
        self.assertEqual(len(report["rejected"]), 1)
        self.assertTrue(report["rejected"][0]["parallel_candidate"])
        self.assertFalse(report["rejected"][0]["executable_parallel"])


if __name__ == "__main__":
    unittest.main()
