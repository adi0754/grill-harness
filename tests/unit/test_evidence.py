import copy
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate


def valid_evidence(**changes):
    record = {
        "id": "EVD-001",
        "status": "valid",
        "currentness": "current",
        "command": "python3 -m unittest discover -s tests -p 'test_*.py'",
        "working_directory": "/repo",
        "exit_code": 0,
        "baseline": "abc123",
        "producer": "independent-verifier",
        "reproducible": True,
        "requirements": ["REQ-001"],
        "decisions": ["DEC-001"],
        "tasks": ["TASK-001"],
        "issues": [],
        "executed_at": "2026-07-12T10:00:00+08:00",
        "output_path": "/repo/.evidence/EVD-001.log",
    }
    record.update(changes)
    return record


class EvidenceValidationTests(unittest.TestCase):
    def test_complete_current_evidence_is_valid(self):
        evidence = valid_evidence()
        before = copy.deepcopy(evidence)

        report = validate.validate_evidence(evidence, current_baseline="abc123")

        self.assertTrue(report["valid"])
        self.assertEqual(report["conflicts"], [])
        self.assertEqual(evidence, before)

    def test_evidence_requires_stable_id_and_absolute_working_directory(self):
        cases = (
            ({"id": ""}, "EVIDENCE_ID"),
            ({"id": None}, "EVIDENCE_ID"),
            ({"working_directory": "."}, "EVIDENCE_WORKING_DIRECTORY"),
        )

        for changes, code in cases:
            with self.subTest(changes=changes):
                report = validate.validate_evidence(
                    valid_evidence(**changes), current_baseline="abc123"
                )
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_command_and_working_directory_must_be_non_empty_strings(self):
        cases = (
            ("command", "", "EVIDENCE_COMMAND"),
            ("command", ["python3", "-m", "unittest"], "EVIDENCE_COMMAND"),
            ("working_directory", "   ", "EVIDENCE_WORKING_DIRECTORY"),
            ("working_directory", None, "EVIDENCE_WORKING_DIRECTORY"),
        )

        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                report = validate.validate_evidence(
                    valid_evidence(**{field: value}), current_baseline="abc123"
                )
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_exit_code_must_be_integer_zero(self):
        for exit_code in (None, True, "0", 1):
            with self.subTest(exit_code=exit_code):
                report = validate.validate_evidence(
                    valid_evidence(exit_code=exit_code), current_baseline="abc123"
                )
                self.assertFalse(report["valid"])
                self.assertIn(
                    "EVIDENCE_EXIT_CODE",
                    {item["code"] for item in report["conflicts"]},
                )

    def test_baseline_is_required_and_must_match_current_repository(self):
        for baseline in (None, "", "old456"):
            with self.subTest(baseline=baseline):
                report = validate.validate_evidence(
                    valid_evidence(baseline=baseline), current_baseline="abc123"
                )
                self.assertFalse(report["valid"])
                self.assertIn(
                    "EVIDENCE_BASELINE",
                    {item["code"] for item in report["conflicts"]},
                )

    def test_producer_and_reproducibility_are_required(self):
        cases = (
            ({"producer": ""}, "EVIDENCE_PRODUCER"),
            ({"producer": None}, "EVIDENCE_PRODUCER"),
            ({"reproducible": False}, "EVIDENCE_REPRODUCIBILITY"),
            ({"reproducible": "yes"}, "EVIDENCE_REPRODUCIBILITY"),
        )

        for changes, code in cases:
            with self.subTest(changes=changes):
                report = validate.validate_evidence(
                    valid_evidence(**changes), current_baseline="abc123"
                )
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_traceability_execution_time_and_output_location_are_required(self):
        cases = (
            (
                {"requirements": [], "decisions": [], "tasks": [], "issues": []},
                "EVIDENCE_TRACEABILITY",
            ),
            ({"tasks": "TASK-001"}, "EVIDENCE_TRACEABILITY"),
            ({"executed_at": ""}, "EVIDENCE_EXECUTED_AT"),
            ({"output_path": ""}, "EVIDENCE_OUTPUT_PATH"),
            ({"output_path": "relative.log"}, "EVIDENCE_OUTPUT_PATH"),
        )

        for changes, code in cases:
            with self.subTest(changes=changes):
                report = validate.validate_evidence(
                    valid_evidence(**changes), current_baseline="abc123"
                )
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_stale_or_nonvalid_evidence_is_rejected_even_if_fields_are_complete(self):
        cases = (
            {"status": "stale"},
            {"currentness": "stale"},
            {"status": "valid", "currentness": "current", "stale_because": "DEC-001"},
        )

        for changes in cases:
            with self.subTest(changes=changes):
                report = validate.validate_evidence(
                    valid_evidence(**changes), current_baseline="abc123"
                )
                self.assertFalse(report["valid"])
                self.assertIn(
                    "STALE_EVIDENCE",
                    {item["code"] for item in report["conflicts"]},
                )

    def test_every_conflict_has_machine_code_and_chinese_recovery(self):
        report = validate.validate_evidence({}, current_baseline="abc123")

        self.assertFalse(report["valid"])
        self.assertGreaterEqual(len(report["conflicts"]), 6)
        for conflict in report["conflicts"]:
            self.assertTrue(conflict["code"])
            self.assertRegex(
                conflict["conflict"] + conflict["recovery_action"],
                "[\u4e00-\u9fff]",
            )


if __name__ == "__main__":
    unittest.main()
