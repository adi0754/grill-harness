import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import state


class WorkflowStateMachineTests(unittest.TestCase):
    def test_workflow_phases_have_a_complete_stable_order(self):
        self.assertEqual(
            state.WORKFLOW_PHASES,
            (
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
            ),
        )

    def test_every_state_pair_matches_the_declared_transition_contract(self):
        legal = {
            "pending": {
                "in_progress", "stale", "skipped", "cancelled", "superseded",
            },
            "in_progress": {
                "needs_user", "blocked", "completed", "failed", "cancelled",
                "stale", "superseded",
            },
            "needs_user": {
                "in_progress", "blocked", "cancelled", "stale", "superseded",
            },
            "blocked": {
                "in_progress", "failed", "cancelled", "stale", "superseded",
            },
            "completed": {"stale", "superseded"},
            "stale": {"in_progress", "superseded", "cancelled"},
            "superseded": set(),
            "skipped": {"stale", "superseded"},
            "failed": {"in_progress", "cancelled", "superseded"},
            "cancelled": set(),
        }

        self.assertEqual(set(state.WORKFLOW_STATES), set(legal))
        for source in state.WORKFLOW_STATES:
            for target in state.WORKFLOW_STATES:
                with self.subTest(source=source, target=target):
                    self.assertEqual(
                        state.can_transition(source, target),
                        target in legal[source],
                    )

    def test_unknown_states_are_rejected_instead_of_treated_as_transitions(self):
        with self.assertRaisesRegex(ValueError, "unknown workflow state"):
            state.can_transition("invented", "pending")

    def test_illegal_transition_explains_source_and_target(self):
        with self.assertRaisesRegex(
            state.InvalidTransition,
            "completed.*in_progress",
        ):
            state.validate_transition("completed", "in_progress")

    def test_three_human_gates_are_explicit_and_require_needs_user(self):
        self.assertEqual(
            state.HUMAN_GATES,
            (
                "requirements_baseline",
                "route_selection",
                "final_spec_approval",
            ),
        )
        for gate in state.HUMAN_GATES:
            with self.subTest(gate=gate):
                with self.assertRaisesRegex(state.StateContractError, "needs_user"):
                    state.validate_human_gate(gate, "in_progress")
                state.validate_human_gate(gate, "needs_user")

    def test_downstream_phase_requires_an_artifact_bound_user_approval(self):
        gates = {
            "requirements_baseline": {
                "status": "approved",
                "approval_id": "DEC-001",
                "artifact_versions": {"baseline": 1},
            },
            "route_selection": {
                "status": "approved",
                "approval_id": "DEC-002",
                "artifact_versions": {"route-card": 1},
            },
            "final_spec_approval": {
                "status": "awaiting_user",
                "artifact_versions": {"spec": 2},
            },
        }

        state.validate_phase_entry("design", gates)
        state.validate_phase_entry("repository_challenge", gates)
        with self.assertRaisesRegex(state.StateContractError, "final_spec_approval"):
            state.validate_phase_entry("implementation", gates)

        gates["final_spec_approval"].update(
            {"status": "approved", "approval_id": "DEC-003"}
        )
        state.validate_phase_entry("implementation", gates)

    def test_phase_entry_is_fail_closed_and_aliases_cannot_bypass_gates(self):
        approved = {
            gate: {
                "status": "approved",
                "approval_id": "DEC-00{}".format(index),
                "artifact_versions": {gate: 1},
            }
            for index, gate in enumerate(state.HUMAN_GATES, start=1)
        }
        for unknown in ("implement", "implementation_loop", "assurance", "unknown"):
            with self.subTest(unknown=unknown):
                with self.assertRaisesRegex(state.StateContractError, "unknown phase"):
                    state.validate_phase_entry(unknown, approved)

        for guarded in ("tasking", "implementation", "independent_assurance"):
            with self.subTest(guarded=guarded):
                gates = dict(approved)
                gates.pop("final_spec_approval")
                with self.assertRaisesRegex(
                    state.StateContractError, "final_spec_approval"
                ):
                    state.validate_phase_entry(guarded, gates)

    def test_approval_without_artifact_version_is_not_a_valid_gate(self):
        gate = {"status": "approved", "approval_id": "DEC-001", "artifact_versions": {}}
        with self.assertRaisesRegex(state.StateContractError, "artifact version"):
            state.validate_gate_contract("requirements_baseline", gate)

    def test_completed_phase_requires_artifacts_and_evidence(self):
        for phase in (
            {
                "id": "phase-1", "status": "completed",
                "artifacts": [], "evidence": ["EVD-001"],
            },
            {
                "id": "phase-1", "status": "completed",
                "artifacts": ["spec.md"], "evidence": [],
            },
        ):
            with self.subTest(phase=phase):
                with self.assertRaises(state.StateContractError):
                    state.validate_phase(phase)

        state.validate_phase(
            {
                "id": "phase-1",
                "status": "completed",
                "artifacts": ["spec.md"],
                "evidence": ["EVD-001"],
            }
        )

    def test_completed_phase_rejects_malformed_artifact_and_evidence_id_sequences(self):
        invalid_values = (
            "EVD-001",
            {"EVD-001": True},
            [""],
            ["   "],
            ["EVD-001", 2],
        )
        for field in ("artifacts", "evidence"):
            for invalid in invalid_values:
                phase = {
                    "id": "specification",
                    "status": "completed",
                    "artifacts": ["spec-v1"],
                    "evidence": ["EVD-001"],
                }
                phase[field] = invalid
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaisesRegex(
                        state.StateContractError, "non-empty string IDs"
                    ):
                        state.validate_phase(phase)

    def test_transition_state_atomically_validates_completion_contract(self):
        phase = {
            "id": "specification",
            "status": "in_progress",
            "artifacts": [],
            "evidence": [],
        }
        with self.assertRaises(state.StateContractError):
            state.transition_state(phase, "completed")

        completed = state.transition_state(
            dict(phase, artifacts=["spec-v1"], evidence=["EVD-001"]),
            "completed",
            gates={
                "route_selection": {
                    "status": "approved",
                    "approval_id": "DEC-002",
                    "artifact_versions": {"route-card": 1},
                }
            },
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(phase["status"], "in_progress")

    def test_transition_state_rejects_string_only_mutation_calls(self):
        with self.assertRaisesRegex(state.StateContractError, "complete phase record"):
            state.transition_state("in_progress", "completed")

    def test_transition_state_cannot_complete_a_guarded_phase_without_approval(self):
        phase = {
            "id": "implementation",
            "status": "in_progress",
            "artifacts": ["implementation-v1"],
            "evidence": ["EVD-001"],
        }
        with self.assertRaisesRegex(state.StateContractError, "final_spec_approval"):
            state.transition_state(phase, "completed")

    def test_skipped_phase_must_be_optional_and_record_a_reason(self):
        with self.assertRaises(state.StateContractError):
            state.validate_phase(
                {
                    "id": "phase-1", "status": "skipped",
                    "optional": False, "skip_reason": "省略",
                }
            )

    def test_knowledge_archive_prerequisites_require_current_acceptance_and_user_approval(self):
        workflow = {
            "git_baseline": "current-commit",
            "phases": [{"id": "independent_assurance", "status": "completed"}],
            "evidence": [{
                "id": "EVD-001", "kind": "final_acceptance", "status": "completed",
                "result": "accepted", "current": True, "baseline": "current-commit",
            }],
            "archive_confirmation": {"status": "approved"},
        }
        self.assertEqual(state.knowledge_archive_prerequisites(workflow), [])

        workflow["evidence"][0]["current"] = False
        self.assertEqual(
            state.knowledge_archive_prerequisites(workflow),
            ["current_acceptance_passed"],
        )

    def test_knowledge_archive_rejects_acceptance_from_a_different_or_missing_baseline(self):
        workflow = {
            "git_baseline": "current-commit",
            "phases": [{"id": "independent_assurance", "status": "completed"}],
            "evidence": [{
                "id": "EVD-001", "kind": "final_acceptance", "status": "valid",
                "result": "accepted", "currentness": "current", "baseline": "old-commit",
            }],
            "archive_confirmation": True,
        }
        for baseline in ("old-commit", None):
            with self.subTest(baseline=baseline):
                workflow["evidence"][0]["baseline"] = baseline
                self.assertIn(
                    "current_acceptance_passed",
                    state.knowledge_archive_prerequisites(workflow),
                )
        with self.assertRaises(state.StateContractError):
            state.validate_phase(
                {
                    "id": "phase-1", "status": "skipped",
                    "optional": True, "skip_reason": "",
                }
            )


if __name__ == "__main__":
    unittest.main()
