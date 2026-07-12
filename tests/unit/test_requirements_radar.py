import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import requirements_radar


class RequirementsRadarTests(unittest.TestCase):
    def radar(self, category="clarification", **changes):
        record = {
            "id": "RAD-001",
            "type": "RAD",
            "version": 1,
            "category": category,
            "summary": "确认退款触发条件",
            "evidence": ["src/refunds.py:refund"],
            "confidence": "high",
            "impact": "错误条件会扩大退款范围",
            "owner": "main-agent",
            "blocking_level": "baseline",
            "status": "open",
            "requirements": ["REQ-001"],
            "decisions": [],
            "risk_signals": {},
            "escalation": "low",
        }
        record.update(changes)
        return record

    def test_all_five_radar_categories_are_valid(self):
        for category in (
            "clarification",
            "omission",
            "implication",
            "paradox",
            "analogue",
        ):
            with self.subTest(category=category):
                report = requirements_radar.validate_radar_record(
                    self.radar(category=category)
                )
                self.assertTrue(report["valid"], report)

    def test_radar_records_require_stable_identity_and_trace_fields(self):
        record = self.radar(id="REQ-001", evidence=[], requirements=[], decisions=[])

        report = requirements_radar.validate_radar_record(record)

        self.assertFalse(report["valid"])
        fields = {item["field"] for item in report["conflicts"]}
        self.assertTrue({"id", "evidence", "traceability"}.issubset(fields), report)

    def test_escalation_classifies_low_medium_and_high_risk(self):
        self.assertEqual(
            requirements_radar.classify_escalation({}),
            {"level": "low", "independent_investigation": False},
        )
        self.assertEqual(
            requirements_radar.classify_escalation(
                {"multiple_inconsistent_precedents": True}
            ),
            {"level": "medium", "independent_investigation": False},
        )
        self.assertEqual(
            requirements_radar.classify_escalation(
                {"public_contract_change": True}
            ),
            {"level": "high", "independent_investigation": True},
        )

    def test_high_risk_investigation_is_explicit_and_user_controlled(self):
        record = self.radar(
            escalation="high",
            risk_signals={"public_contract_change": True},
            investigation_plan={
                "reason": "公共 Schema 变化",
                "question": "哪些消费者必须同步迁移？",
                "role": "repository-investigator",
                "expected_output": "调用方与迁移影响清单",
                "blocks_baseline": True,
                "agent_selection": "needs_user",
            },
        )
        self.assertTrue(requirements_radar.validate_radar_record(record)["valid"])

        record["investigation_plan"]["agent_selection"] = "auto-dispatched"
        report = requirements_radar.validate_radar_record(record)
        self.assertFalse(report["valid"])
        self.assertIn("user", report["conflicts"][0]["conflict"])

    def test_escalation_cannot_be_missing_or_downgraded_from_risk_signals(self):
        missing = self.radar()
        del missing["escalation"]
        missing_report = requirements_radar.validate_radar_record(missing)
        self.assertFalse(missing_report["valid"])
        self.assertEqual(missing_report["conflicts"][0]["field"], "escalation")

        downgraded = self.radar(
            escalation="medium",
            risk_signals={"schema_change": True},
        )
        downgraded_report = requirements_radar.validate_radar_record(downgraded)
        self.assertFalse(downgraded_report["valid"])
        self.assertTrue(
            any(item["field"] == "escalation" for item in downgraded_report["conflicts"])
        )

    def test_derived_high_risk_cannot_omit_investigation_plan(self):
        record = self.radar(
            escalation="high",
            risk_signals={"impact_unknown": True},
        )
        report = requirements_radar.validate_radar_record(record)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any(item["field"] == "investigation_plan" for item in report["conflicts"])
        )

    def test_only_current_open_baseline_records_block_approval(self):
        records = [
            self.radar(id="RAD-001", status="open"),
            self.radar(id="RAD-002", status="resolved"),
            self.radar(id="RAD-003", blocking_level="implementation"),
            self.radar(id="RAD-004", status="superseded"),
            self.radar(id="RAD-005", version=1, status="open"),
            self.radar(id="RAD-005", version=2, status="resolved"),
        ]
        self.assertEqual(
            requirements_radar.unresolved_baseline_blockers(records), ["RAD-001"]
        )

    def test_analogue_candidate_requires_complete_comparison(self):
        comparison = {
            "status": "found",
            "candidates": [{"path": "src/orders.py", "symbol": "create_order"}],
        }

        report = requirements_radar.validate_analogue_comparison(comparison)

        self.assertFalse(report["valid"])
        fields = {item["field"] for item in report["conflicts"]}
        self.assertEqual(
            fields,
            {
                "similarities",
                "differences",
                "reusable_parts",
                "non_reuse_reasons",
                "shared_contracts",
                "reusable_tests",
                "new_behavior",
            },
        )

    def test_complete_analogue_candidate_is_valid(self):
        comparison = {
            "status": "found",
            "candidates": [
                {
                    "path": "src/orders.py",
                    "symbol": "create_order",
                    "similarities": ["相同的幂等键"],
                    "differences": ["退款由事件触发"],
                    "reusable_parts": ["幂等校验"],
                    "non_reuse_reasons": ["订单状态机不同"],
                    "shared_contracts": ["events.OrderChanged"],
                    "reusable_tests": ["tests/test_orders.py:test_idempotency"],
                    "new_behavior": ["退款失败补偿"],
                }
            ],
        }
        self.assertTrue(
            requirements_radar.validate_analogue_comparison(comparison)["valid"]
        )

    def test_not_found_analogue_requires_search_scope_and_evidence(self):
        report = requirements_radar.validate_analogue_comparison(
            {"status": "not_found", "search_scope": ["src"]}
        )
        self.assertFalse(report["valid"])
        self.assertEqual(report["conflicts"][0]["field"], "search_evidence")

        valid = requirements_radar.validate_analogue_comparison(
            {
                "status": "not_found",
                "search_scope": ["src", "tests"],
                "search_evidence": ["rg -n 'refund|compensation' src tests"],
            }
        )
        self.assertTrue(valid["valid"], valid)

    def test_traceability_reports_missing_radar_links_across_artifacts(self):
        records = [self.radar(id="RAD-001"), self.radar(id="RAD-002")]
        artifacts = {
            "route_card": {"radar_ids": ["RAD-001", "RAD-002"]},
            "repository_challenge": {"radar_ids": ["RAD-001"]},
            "final_spec": {"radar_ids": ["RAD-001", "RAD-002"]},
            "tasks": {"radar_ids": ["RAD-001", "RAD-002"]},
            "acceptance": {"radar_ids": ["RAD-001", "RAD-002"]},
            "knowledge": {"radar_ids": ["RAD-001", "RAD-002"]},
        }

        report = requirements_radar.traceability_report(records, artifacts)

        self.assertFalse(report["valid"])
        self.assertEqual(
            report["missing"], {"repository_challenge": ["RAD-002"]}
        )

    def test_traceability_rejects_string_and_invalid_radar_id_contracts(self):
        records = [self.radar(id="RAD-001")]
        artifacts = {
            name: {"radar_ids": ["RAD-001"]}
            for name in requirements_radar.TRACE_ARTIFACTS
        }
        artifacts["route_card"] = {"radar_ids": "RAD-001"}
        artifacts["final_spec"] = {"radar_ids": ["REQ-001"]}

        report = requirements_radar.traceability_report(records, artifacts)

        self.assertFalse(report["valid"])
        self.assertEqual(
            {item["artifact"] for item in report["conflicts"]},
            {"route_card", "final_spec"},
        )


if __name__ == "__main__":
    unittest.main()
