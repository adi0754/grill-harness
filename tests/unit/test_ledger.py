import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import state


class LedgerContractTests(unittest.TestCase):
    def test_supported_record_types_have_stable_padded_ids(self):
        prefixes = ("REQ", "DEC", "CON", "RISK", "CHG", "TASK", "ISSUE", "EVD")
        self.assertEqual(state.LEDGER_RECORD_TYPES, prefixes)
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                self.assertEqual(state.format_record_id(prefix, 1), "{}-001".format(prefix))
                self.assertEqual(state.format_record_id(prefix, 27), "{}-027".format(prefix))

    def test_revising_a_record_keeps_its_id_and_increments_its_version(self):
        original = state.create_ledger_record("DEC", 3, {"summary": "使用轮询"})
        revised = state.revise_ledger_record(
            original, {"summary": "使用事件"}, expected_version=1
        )
        revised_again = state.revise_ledger_record(
            revised, {"reason": "仓库事实变化"}, expected_version=2
        )

        self.assertEqual(original["id"], "DEC-003")
        self.assertEqual(revised["id"], original["id"])
        self.assertEqual(revised_again["id"], original["id"])
        self.assertEqual([original["version"], revised["version"], revised_again["version"]], [1, 2, 3])
        self.assertEqual(original["summary"], "使用轮询")

    def test_revisions_cannot_silently_change_identity_or_version(self):
        record = state.create_ledger_record("REQ", 1, {"summary": "保留离线模式"})
        with self.assertRaises(state.LedgerContractError):
            state.revise_ledger_record(record, {"id": "REQ-002"})
        with self.assertRaises(state.LedgerContractError):
            state.revise_ledger_record(record, {"version": 99})

        with self.assertRaisesRegex(state.LedgerContractError, "expected version"):
            state.revise_ledger_record(record, {"summary": "冲突写入"}, expected_version=2)

    def test_ledger_rejects_duplicate_ids_and_non_contiguous_versions(self):
        duplicate = [
            {"id": "RISK-001", "type": "RISK", "version": 1},
            {"id": "RISK-001", "type": "RISK", "version": 1},
        ]
        with self.assertRaises(state.LedgerContractError):
            state.validate_ledger(duplicate)

        with self.assertRaises(state.LedgerContractError):
            state.validate_ledger_history(
                [
                    {"id": "CHG-001", "type": "CHG", "version": 1},
                    {"id": "CHG-001", "type": "CHG", "version": 3},
                ]
            )

    def test_top_level_ledger_validator_accepts_contiguous_history(self):
        state.validate_ledger(
            [
                {"id": "DEC-001", "type": "DEC", "version": 1},
                {"id": "DEC-001", "type": "DEC", "version": 2},
                {"id": "DEC-001", "type": "DEC", "version": 3},
            ]
        )


if __name__ == "__main__":
    unittest.main()
