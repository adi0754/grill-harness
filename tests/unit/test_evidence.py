import copy
import os
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate


CURRENT_TIME = "2026-07-12T12:00:00+08:00"
# os.path.isabs("/repo") is False on Windows (Python 3.13), so build a real
# platform-absolute fixture path instead of hard-coding a POSIX one.
REPO_DIR = os.path.abspath(os.sep + "repo")


def valid_evidence(**changes):
    record = {
        "id": "EVD-001",
        "status": "valid",
        "currentness": "current",
        "command": "python3 -m unittest discover -s tests -p 'test_*.py'",
        "working_directory": REPO_DIR,
        "exit_code": 0,
        "baseline": "abc123",
        "producer": "independent-verifier",
        "reproducible": True,
        "requirements": ["REQ-001"],
        "decisions": ["DEC-001"],
        "tasks": ["TASK-001"],
        "issues": [],
        "executed_at": "2026-07-12T10:00:00+08:00",
        "validated_at": "2026-07-12T10:01:00+08:00",
        "expires_at": "2026-07-13T10:01:00+08:00",
        "output_path": os.path.join(REPO_DIR, ".evidence", "EVD-001.log"),
    }
    record.update(changes)
    return record


def validate_record(record, **changes):
    options = {"current_baseline": "abc123", "current_time": CURRENT_TIME}
    options.update(changes)
    return validate.validate_evidence(record, **options)


class EvidenceValidationTests(unittest.TestCase):
    def test_complete_current_evidence_is_valid(self):
        evidence = valid_evidence()
        before = copy.deepcopy(evidence)

        report = validate_record(evidence)

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
                report = validate_record(valid_evidence(**changes))
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_command_and_working_directory_must_be_non_empty_strings(self):
        cases = (
            ("command", "", "EVIDENCE_COMMAND"),
            ("command", ["python3"], "EVIDENCE_COMMAND"),
            ("working_directory", "   ", "EVIDENCE_WORKING_DIRECTORY"),
            ("working_directory", None, "EVIDENCE_WORKING_DIRECTORY"),
        )
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                report = validate_record(valid_evidence(**{field: value}))
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_exit_code_must_be_integer_zero(self):
        for exit_code in (None, True, "0", 1):
            with self.subTest(exit_code=exit_code):
                report = validate_record(valid_evidence(exit_code=exit_code))
                self.assertFalse(report["valid"])
                self.assertIn("EVIDENCE_EXIT_CODE", {item["code"] for item in report["conflicts"]})

    def test_baseline_is_required_and_must_match_current_repository(self):
        for baseline in (None, "", "old456"):
            with self.subTest(baseline=baseline):
                report = validate_record(valid_evidence(baseline=baseline))
                self.assertFalse(report["valid"])
                self.assertIn("EVIDENCE_BASELINE", {item["code"] for item in report["conflicts"]})

    def test_producer_and_reproducibility_are_required(self):
        cases = (
            ({"producer": ""}, "EVIDENCE_PRODUCER"),
            ({"producer": None}, "EVIDENCE_PRODUCER"),
            ({"reproducible": False}, "EVIDENCE_REPRODUCIBILITY"),
            ({"reproducible": "yes"}, "EVIDENCE_REPRODUCIBILITY"),
        )
        for changes, code in cases:
            with self.subTest(changes=changes):
                report = validate_record(valid_evidence(**changes))
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_traceability_and_output_location_are_required(self):
        cases = (
            ({"requirements": [], "decisions": [], "tasks": [], "issues": []}, "EVIDENCE_TRACEABILITY"),
            ({"tasks": "TASK-001"}, "EVIDENCE_TRACEABILITY"),
            ({"output_path": ""}, "EVIDENCE_OUTPUT_PATH"),
            ({"output_path": "relative.log"}, "EVIDENCE_OUTPUT_PATH"),
        )
        for changes, code in cases:
            with self.subTest(changes=changes):
                report = validate_record(valid_evidence(**changes))
                self.assertFalse(report["valid"])
                self.assertIn(code, {item["code"] for item in report["conflicts"]})

    def test_execution_and_validity_timestamps_require_timezone_aware_iso_8601(self):
        for field in ("executed_at", "validated_at", "expires_at"):
            for value in ("", "not-a-time", "2026-07-12T10:00:00"):
                with self.subTest(field=field, value=value):
                    report = validate_record(valid_evidence(**{field: value}))
                    self.assertFalse(report["valid"])
                    self.assertIn("EVIDENCE_TIME", {item["code"] for item in report["conflicts"]})

    def test_expired_or_not_yet_validated_evidence_is_stale_at_explicit_time(self):
        cases = (
            {"expires_at": "2026-07-12T11:59:59+08:00"},
            {"validated_at": "2026-07-12T12:01:00+08:00"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                report = validate_record(valid_evidence(**changes))
                self.assertFalse(report["valid"])
                self.assertIn("STALE_EVIDENCE", {item["code"] for item in report["conflicts"]})

    def test_current_time_is_explicit_and_timezone_aware(self):
        for current_time in (None, "not-a-time", "2026-07-12T12:00:00"):
            with self.subTest(current_time=current_time):
                report = validate_record(valid_evidence(), current_time=current_time)
                self.assertFalse(report["valid"])
                self.assertIn("EVIDENCE_CURRENT_TIME", {item["code"] for item in report["conflicts"]})

    def test_stale_or_nonvalid_evidence_is_rejected_even_if_fields_are_complete(self):
        cases = (
            {"status": "stale"},
            {"currentness": "stale"},
            {"status": "valid", "currentness": "current", "stale_because": "DEC-001"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                report = validate_record(valid_evidence(**changes))
                self.assertFalse(report["valid"])
                self.assertIn("STALE_EVIDENCE", {item["code"] for item in report["conflicts"]})

    def test_evidence_collection_rejects_duplicate_ids_and_non_mapping_records(self):
        duplicate_report = validate.validate_evidence_records(
            [valid_evidence(), valid_evidence(command="python3 -m compileall .")],
            current_baseline="abc123",
            current_time=CURRENT_TIME,
        )
        malformed_report = validate.validate_evidence_records(
            [valid_evidence(), "not-a-record"],
            current_baseline="abc123",
            current_time=CURRENT_TIME,
        )

        self.assertFalse(duplicate_report["valid"])
        self.assertIn("DUPLICATE_EVIDENCE_ID", {item["code"] for item in duplicate_report["conflicts"]})
        self.assertFalse(malformed_report["valid"])
        self.assertIn("INVALID_EVIDENCE_RECORD", {item["code"] for item in malformed_report["conflicts"]})

    def test_single_non_mapping_evidence_returns_machine_readable_conflict(self):
        report = validate_record("not-a-record")

        self.assertFalse(report["valid"])
        self.assertEqual(report["conflicts"][0]["code"], "INVALID_EVIDENCE_RECORD")
        self.assertRegex(
            report["conflicts"][0]["conflict"] + report["conflicts"][0]["recovery_action"],
            "[\u4e00-\u9fff]",
        )

    def test_every_conflict_has_machine_code_and_chinese_recovery(self):
        report = validate_record({})

        self.assertFalse(report["valid"])
        self.assertGreaterEqual(len(report["conflicts"]), 6)
        for conflict in report["conflicts"]:
            self.assertTrue(conflict["code"])
            self.assertRegex(conflict["conflict"] + conflict["recovery_action"], "[\u4e00-\u9fff]")


if __name__ == "__main__":
    unittest.main()
