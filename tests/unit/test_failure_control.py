import sys
import unittest
import copy
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "grill-harness"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import failure_control


class FailureControlTests(unittest.TestCase):
    def test_all_four_failure_classes_are_explicit(self):
        self.assertEqual(
            failure_control.FAILURE_CLASSES,
            frozenset(
                {
                    "implementation_failure",
                    "route_failure",
                    "evidence_failure",
                    "workflow_integrity_failure",
                }
            ),
        )

    def test_fingerprint_uses_structured_failure_facts_not_review_wording(self):
        first = failure_control.issue_fingerprint(
            {
                "issue_id": "ISSUE-007",
                "failed_acceptance": ["REQ-004"],
                "failed_command": ["python3 -m unittest tests.unit.test_checkout"],
                "git_baseline": "abc123:clean",
                "summary": "结账测试失败",
            }
        )
        reworded = failure_control.issue_fingerprint(
            {
                "issue_id": "ISSUE-007",
                "failed_acceptance": ["REQ-004"],
                "failed_command": ["python3 -m unittest tests.unit.test_checkout"],
                "git_baseline": "abc123:clean",
                "summary": "Reviewer 用完全不同的话描述同一问题",
            }
        )

        self.assertEqual(first, reworded)
        self.assertRegex(first, r"^FAIL-[0-9a-f]{16}$")

    def test_fingerprint_separates_different_git_baselines(self):
        facts = {
            "issue_id": "ISSUE-007",
            "failed_acceptance": ["REQ-004"],
            "failed_command": [],
            "git_baseline": "abc123:clean",
        }

        first = failure_control.issue_fingerprint(facts)
        second = failure_control.issue_fingerprint(
            dict(facts, git_baseline="def456:dirty:0123")
        )

        self.assertNotEqual(first, second)

    def test_implementation_failure_escalates_on_attempts_one_two_and_three(self):
        actions = [
            failure_control.next_action("implementation_failure", attempt_count=attempt)
            for attempt in (1, 2, 3)
        ]

        self.assertEqual(
            [item["action"] for item in actions],
            ["minimal_fix", "root_cause_recheck", "recover_required"],
        )
        self.assertTrue(actions[0]["ordinary_repair_allowed"])
        self.assertTrue(actions[1]["ordinary_repair_allowed"])
        self.assertFalse(actions[2]["ordinary_repair_allowed"])
        self.assertEqual(actions[2]["recommended_entry"], "grh-recover")

    def test_non_implementation_failures_require_their_bounded_recovery(self):
        route = failure_control.next_action("route_failure")
        evidence = failure_control.next_action("evidence_failure")
        integrity = failure_control.next_action("workflow_integrity_failure")

        self.assertEqual(route["action"], "human_route_selection")
        self.assertTrue(route["requires_user_route_selection"])
        self.assertIsNone(route["selected_route"])
        self.assertFalse(route["will_auto_route"])
        self.assertEqual(evidence["action"], "more_evidence_required")
        self.assertEqual(integrity["action"], "reconcile_required")

    def test_ordinary_bug_never_becomes_an_automatic_route_change(self):
        action = failure_control.next_action(
            "implementation_failure", attempt_count=1
        )

        self.assertFalse(action["route_change_required"])
        self.assertFalse(action["will_auto_route"])
        self.assertIsNone(action["selected_route"])

    def test_threshold_override_requires_user_approved_decision_and_reason(self):
        fingerprint = "FAIL-1111111111111111"
        ledger = [
            {
                "id": "DEC-101",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-101",
                "approved_threshold": 4,
                "reason": "第四轮用于验证已由用户确认的新根因",
            },
            {
                "id": "CHG-102",
                "type": "CHG",
                "version": 1,
                "status": "approved",
                "approved_by": "agent",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-101",
                "approved_threshold": 4,
                "reason": "agent proposed",
            },
            {
                "id": "DEC-999",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "failure_fingerprint": "FAIL-9999999999999999",
                "issue_id": "ISSUE-999",
                "approved_threshold": 999,
                "reason": "unrelated approval",
            },
        ]

        valid = failure_control.validate_threshold_override(
            {
                "threshold": 4,
                "approval_id": "DEC-101",
                "reason": "第四轮用于验证已由用户确认的新根因",
            },
            ledger,
            fingerprint=fingerprint,
            issue_id="ISSUE-101",
        )
        missing_reason = failure_control.validate_threshold_override(
            {"threshold": 4, "approval_id": "DEC-101", "reason": ""},
            ledger,
            fingerprint=fingerprint,
            issue_id="ISSUE-101",
        )
        agent_only = failure_control.validate_threshold_override(
            {
                "threshold": 4,
                "approval_id": "CHG-102",
                "reason": "agent proposed",
            },
            ledger,
            fingerprint=fingerprint,
            issue_id="ISSUE-101",
        )
        unrelated = failure_control.validate_threshold_override(
            {
                "threshold": 4,
                "approval_id": "DEC-999",
                "reason": "第四轮用于验证已由用户确认的新根因",
            },
            ledger,
            fingerprint=fingerprint,
            issue_id="ISSUE-101",
        )
        revised_ledger = ledger + [
            dict(
                ledger[0],
                version=2,
                reason="后续不同批准内容",
            )
        ]
        snapshot_override = {
            "threshold": 4,
            "approval_id": "DEC-101",
            "approval_version": 1,
            "approval_hash": failure_control.approval_record_hash(ledger[0]),
            "reason": "第四轮用于验证已由用户确认的新根因",
        }
        historical_snapshot = failure_control.validate_threshold_override(
            snapshot_override,
            revised_ledger,
            fingerprint=fingerprint,
            issue_id="ISSUE-101",
        )
        forged_snapshot = failure_control.validate_threshold_override(
            dict(snapshot_override, approval_hash="0" * 64),
            revised_ledger,
            fingerprint=fingerprint,
            issue_id="ISSUE-101",
        )

        self.assertTrue(valid["valid"])
        self.assertEqual(valid["threshold"], 4)
        self.assertFalse(missing_reason["valid"])
        self.assertFalse(agent_only["valid"])
        self.assertFalse(unrelated["valid"])
        self.assertTrue(historical_snapshot["valid"])
        self.assertFalse(forged_snapshot["valid"])

    def test_record_attempt_counts_only_the_same_stable_fingerprint(self):
        facts = {
            "failure_class": "implementation_failure",
            "issue_id": "ISSUE-007",
            "failed_acceptance": ["REQ-004"],
            "failed_command": [],
            "git_baseline": "abc123:clean",
            "evidence": ["EVD-007"],
        }
        original = []

        first = failure_control.record_attempt(original, facts)
        second = failure_control.record_attempt(first["history"], facts)
        different_baseline = failure_control.record_attempt(
            second["history"], dict(facts, git_baseline="def456:clean")
        )

        self.assertEqual(original, [])
        self.assertEqual(first["attempt_count"], 1)
        self.assertEqual(second["attempt_count"], 2)
        self.assertEqual(different_baseline["attempt_count"], 1)
        self.assertEqual(second["record"]["action"], "root_cause_recheck")
        self.assertEqual(len(second["history"]), 2)

    def test_repair_chain_keeps_originating_baseline_when_current_baseline_changes(self):
        facts = {
            "failure_class": "implementation_failure",
            "issue_id": "ISSUE-008",
            "failed_acceptance": ["REQ-008"],
            "failed_command": [],
            "originating_baseline": "base-before-repair",
            "current_baseline": "base-before-repair",
        }

        first = failure_control.record_attempt([], facts)
        second = failure_control.record_attempt(
            first["history"],
            dict(facts, current_baseline="base-after-first-repair"),
        )

        self.assertEqual(second["fingerprint"], first["fingerprint"])
        self.assertEqual(second["attempt_count"], 2)
        self.assertEqual(
            second["record"]["originating_baseline"], "base-before-repair"
        )
        self.assertEqual(
            second["record"]["current_baseline"], "base-after-first-repair"
        )

    def test_failure_class_cannot_change_inside_one_fingerprint_chain(self):
        facts = {
            "failure_class": "implementation_failure",
            "issue_id": "ISSUE-009",
            "failed_acceptance": ["REQ-009"],
            "failed_command": [],
            "originating_baseline": "base-009",
            "current_baseline": "base-009",
        }
        first = failure_control.record_attempt([], facts)

        with self.assertRaisesRegex(ValueError, "class"):
            failure_control.record_attempt(
                first["history"], dict(facts, failure_class="route_failure")
            )

    def test_record_attempt_rejects_a_fingerprint_not_derived_from_failure_facts(self):
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            failure_control.record_attempt(
                [],
                {
                    "failure_class": "implementation_failure",
                    "fingerprint": "FAIL-0000000000000000",
                    "issue_id": "ISSUE-007",
                    "failed_acceptance": ["REQ-004"],
                    "failed_command": [],
                    "git_baseline": "abc123:clean",
                    "evidence": ["EVD-007"],
                },
            )

    def test_optional_review_comments_do_not_prevent_evidence_backed_completion(self):
        optional_only = failure_control.next_action(
            "implementation_failure",
            attempt_count=1,
            review_comments=[
                {
                    "id": "ISSUE-OPT",
                    "classification": "optional_optimization",
                    "status": "open",
                },
                {
                    "id": "ISSUE-NO",
                    "classification": "invalid",
                    "status": "rejected",
                },
            ],
            goals_satisfied=True,
            test_evidence_satisfied=True,
        )
        must_fix = failure_control.next_action(
            "implementation_failure",
            attempt_count=1,
            review_comments=[
                {
                    "id": "ISSUE-BLOCK",
                    "classification": "must_fix",
                    "status": "open",
                }
            ],
            goals_satisfied=True,
            test_evidence_satisfied=True,
        )

        self.assertTrue(optional_only["review_converged"])
        self.assertTrue(optional_only["completion_allowed"])
        self.assertEqual(optional_only["optional_review_ids"], ["ISSUE-OPT"])
        self.assertFalse(must_fix["review_converged"])
        self.assertEqual(must_fix["unresolved_review_ids"], ["ISSUE-BLOCK"])

    def test_closed_must_fix_comment_requires_its_own_evidence(self):
        without_evidence = failure_control.next_action(
            "implementation_failure",
            review_comments=[
                {
                    "id": "ISSUE-MUST",
                    "classification": "must_fix",
                    "status": "fixed",
                    "evidence": [],
                }
            ],
        )
        with_evidence = failure_control.next_action(
            "implementation_failure",
            review_comments=[
                {
                    "id": "ISSUE-MUST",
                    "classification": "must_fix",
                    "status": "fixed",
                    "evidence": ["EVD-901"],
                }
            ],
        )

        self.assertFalse(without_evidence["review_converged"])
        self.assertEqual(
            without_evidence["missing_review_evidence_ids"], ["ISSUE-MUST"]
        )
        self.assertTrue(with_evidence["review_converged"])

    def test_repair_template_carries_failure_history_evidence_and_stop_rule(self):
        template = (
            SCRIPTS.parent / "assets" / "templates" / "修复任务.md"
        ).read_text(encoding="utf-8")

        for field in (
            "失败分类",
            "稳定指纹",
            "当前修复轮次",
            "修复历史",
            "失败证据",
            "停止条件",
            "grh-recover",
        ):
            self.assertIn(field, template)

    def test_failure_manifest_hash_chain_detects_modification_and_deletion(self):
        facts = {
            "failure_class": "implementation_failure",
            "issue_id": "ISSUE-800",
            "failed_acceptance": ["REQ-800"],
            "failed_command": [],
            "originating_baseline": "origin-800",
            "current_baseline": "current-800",
        }
        first = failure_control.record_attempt([], facts)
        first_record = failure_control.seal_failure_record(first["record"], None)
        second = failure_control.record_attempt([first_record], facts)
        second_record = failure_control.seal_failure_record(
            second["record"], first_record["record_hash"]
        )
        records = [first_record, second_record]
        manifest = failure_control.failure_chain_manifest(records)

        self.assertTrue(
            failure_control.validate_failure_chain(records, manifest)["valid"]
        )
        modified = copy.deepcopy(records)
        modified[0]["action"] = "root_cause_recheck"
        self.assertFalse(
            failure_control.validate_failure_chain(modified, manifest)["valid"]
        )
        self.assertFalse(
            failure_control.validate_failure_chain(records[1:], manifest)["valid"]
        )

    def test_failure_chain_rejects_a_threshold_override_without_snapshot(self):
        facts = {
            "failure_class": "implementation_failure",
            "issue_id": "ISSUE-801",
            "failed_acceptance": ["REQ-801"],
            "failed_command": [],
            "originating_baseline": "origin-801",
            "current_baseline": "current-801",
        }
        fingerprint = failure_control.issue_fingerprint(facts)
        approval = {
            "id": "DEC-801",
            "type": "DEC",
            "version": 1,
            "status": "approved",
            "approved_by": "user",
            "failure_fingerprint": fingerprint,
            "issue_id": "ISSUE-801",
            "approved_threshold": 4,
            "reason": "approve fourth attempt",
        }
        attempt = failure_control.record_attempt(
            [],
            facts,
            threshold_override={
                "threshold": 4,
                "approval_id": "DEC-801",
                "reason": "approve fourth attempt",
            },
            ledger=[approval],
        )["record"]
        attempt["threshold_override"].pop("approval_version")
        attempt["threshold_override"].pop("approval_hash")
        sealed = failure_control.seal_failure_record(attempt, None)

        report = failure_control.validate_failure_chain([sealed], ledger=[approval])

        self.assertFalse(report["valid"])
        self.assertIn("snapshot", report["conflicts"][0]["conflict"])


if __name__ == "__main__":
    unittest.main()
