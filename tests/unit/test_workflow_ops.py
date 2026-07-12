import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "grill-harness" / "scripts" / "grh.py"
SCRIPTS = CLI.parent
sys.path.insert(0, str(SCRIPTS))

import grh
import failure_control
import state
import workflow_ops


def run_cli(*arguments, env=None):
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class WorkflowOperationTests(unittest.TestCase):
    def _workflow(self, base):
        root = base / "storage"
        project = base / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        subprocess.run(["git", "-C", str(project), "config", "user.name", "Tests"], check=True)
        subprocess.run(["git", "-C", str(project), "config", "user.email", "tests@example.com"], check=True)
        (project / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(project), "commit", "-qm", "init"], check=True)
        env = dict(os.environ)
        env["GRILL_HARNESS_TEST_ROOT"] = str(root)
        result = run_cli(
            "init", "--project", str(project), "--workflow-name", "操作检查",
            "--workflow-key", "ops", "--created-date", "2026-07-12", env=env,
        )
        return env, Path(json.loads(result.stdout)["workflow_path"])

    def test_record_gate_and_transition_are_guarded_and_sync_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._workflow(Path(directory))
            spec_path = workflow / "最终产物" / "最终规格.md"
            spec_path.write_text("spec", encoding="utf-8")
            record_path = workflow / "系统" / "artifact-record.yaml"
            record_path.write_text(
                json.dumps({
                    "id": "ART-001", "status": "completed", "version": 1,
                    "kind": "final-spec",
                    "currentness": "current", "path": str(spec_path),
                    "decisions": ["DEC-003"],
                }),
                encoding="utf-8",
            )

            registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "artifact",
                "--record", str(record_path), env=env,
            )
            forged = run_cli(
                "approve", "--workflow", str(workflow),
                "--gate", "final_spec_approval", "--approval-id", "DEC-003",
                "--artifact-version", "ART-001=1", env=env,
            )
            ledger_record = workflow / "系统" / "ledger-record.yaml"
            ledger_record.write_text(
                json.dumps({
                    "id": "DEC-003",
                    "type": "DEC",
                    "version": 1,
                    "summary": "用户批准最终规格",
                    "status": "approved",
                    "approved_by": "user",
                    "gate": "final_spec_approval",
                    "artifact_versions": {"ART-001": 1},
                }),
                encoding="utf-8",
            )
            ledger_registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "ledger",
                "--record", str(ledger_record), env=env,
            )
            approved = run_cli(
                "approve", "--workflow", str(workflow),
                "--gate", "final_spec_approval", "--approval-id", "DEC-003",
                "--artifact-version", "ART-001=1", env=env,
            )
            out_of_order = run_cli(
                "transition", "--workflow", str(workflow),
                "--phase", "implementation", "--to", "in_progress", env=env,
            )
            transitioned = run_cli(
                "transition", "--workflow", str(workflow),
                "--phase", "preflight", "--to", "in_progress", env=env,
            )

            self.assertEqual(registered.returncode, 0, registered.stdout)
            self.assertEqual(forged.returncode, 2, forged.stdout)
            self.assertEqual(ledger_registered.returncode, 0, ledger_registered.stdout)
            self.assertEqual(approved.returncode, 0, approved.stdout)
            self.assertEqual(out_of_order.returncode, 2, out_of_order.stdout)
            self.assertIn(
                "previous phases",
                json.loads(out_of_order.stdout)["error"]["message"],
            )
            self.assertEqual(transitioned.returncode, 0, transitioned.stdout)
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            manifest = json.loads(
                (workflow / "系统" / "artifacts.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(state_payload["artifacts"], manifest["artifacts"])
            tasking = next(
                item for item in state_payload["phases"] if item["id"] == "preflight"
            )
            self.assertEqual(tasking["status"], "in_progress")

    def test_requirements_gate_rejects_open_baseline_radar_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._workflow(Path(directory))
            state_path = workflow / "系统" / "state.yaml"
            before = state_path.read_text(encoding="utf-8")
            baseline_path = workflow / "核心文档" / "需求基线.md"
            baseline_path.write_text("baseline", encoding="utf-8")
            artifact_record = workflow / "系统" / "baseline-artifact.yaml"
            artifact_record.write_text(
                json.dumps({
                    "id": "ART-BASELINE",
                    "status": "completed",
                    "version": 1,
                    "kind": "requirements-baseline",
                    "currentness": "current",
                    "path": str(baseline_path),
                    "decisions": ["DEC-002"],
                }),
                encoding="utf-8",
            )
            artifact_registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "artifact",
                "--record", str(artifact_record), env=env,
            )
            approval_record = workflow / "系统" / "baseline-approval.yaml"
            approval_record.write_text(
                json.dumps({
                    "id": "DEC-002",
                    "type": "DEC",
                    "version": 1,
                    "summary": "用户批准需求基线",
                    "status": "approved",
                    "approved_by": "user",
                    "gate": "requirements_baseline",
                    "artifact_versions": {"ART-BASELINE": 1},
                }),
                encoding="utf-8",
            )
            approval_registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "ledger",
                "--record", str(approval_record), env=env,
            )
            ledger_record = workflow / "系统" / "radar-record.yaml"
            ledger_record.write_text(
                json.dumps({
                    "id": "RAD-001",
                    "type": "RAD",
                    "version": 1,
                    "category": "paradox",
                    "summary": "期限与回滚要求冲突",
                    "evidence": ["requirements.md"],
                    "confidence": "high",
                    "impact": "路线可能全部失效",
                    "owner": "user",
                    "blocking_level": "baseline",
                    "status": "open",
                    "risk_signals": {"constraint_conflict": True},
                    "escalation": "high",
                    "investigation_plan": {
                        "reason": "期限与回滚要求冲突",
                        "question": "是否存在同时满足两项约束的路线？",
                        "role": "repository-investigator",
                        "expected_output": "约束可行性证据",
                        "blocks_baseline": True,
                        "agent_selection": "needs_user",
                    },
                    "requirements": ["REQ-001"],
                    "decisions": [],
                }),
                encoding="utf-8",
            )
            registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "ledger",
                "--record", str(ledger_record), env=env,
            )
            before_approval = state_path.read_text(encoding="utf-8")

            result = run_cli(
                "approve", "--workflow", str(workflow),
                "--gate", "requirements_baseline", "--approval-id", "DEC-002",
                "--artifact-version", "ART-BASELINE=1", env=env,
            )

            self.assertEqual(artifact_registered.returncode, 0, artifact_registered.stdout)
            self.assertEqual(approval_registered.returncode, 0, approval_registered.stdout)
            self.assertEqual(registered.returncode, 0, registered.stdout)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("RAD-001", json.loads(result.stdout)["error"]["message"])
            self.assertNotEqual(before, before_approval)
            self.assertEqual(state_path.read_text(encoding="utf-8"), before_approval)

    def test_mutations_refuse_paths_outside_harness_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._workflow(Path(directory))
            outside = Path(directory) / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            record = Path(directory) / "record.yaml"
            record.write_text(
                json.dumps({
                    "id": "ART-OUT", "status": "completed", "version": 1,
                    "currentness": "current", "path": str(outside),
                    "decisions": ["DEC-001"],
                }),
                encoding="utf-8",
            )

            result = run_cli(
                "record", "--workflow", str(workflow), "--kind", "artifact",
                "--record", str(record), env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("current workflow", json.loads(result.stdout)["error"]["message"])

    def test_evidence_registration_requires_and_persists_current_project_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env, workflow = self._workflow(base)
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            project = base / "project"
            output = workflow / "过程产物" / "实施报告" / "evidence.log"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok\n", encoding="utf-8")
            record = workflow / "系统" / "evidence-record.yaml"
            record.write_text(
                json.dumps({
                    "id": "EVD-001",
                    "status": "valid",
                    "currentness": "current",
                    "command": "python3 -m unittest",
                    "working_directory": str(project),
                    "exit_code": 0,
                    "baseline": state_payload["git_baseline"],
                    "producer": "independent-verifier",
                    "reproducible": True,
                    "requirements": ["REQ-001"],
                    "decisions": [],
                    "tasks": [],
                    "issues": [],
                    "executed_at": "2026-07-11T20:00:00+08:00",
                    "validated_at": "2026-07-11T20:01:00+08:00",
                    "expires_at": "2099-07-12T20:01:00+08:00",
                    "output_path": str(output),
                }),
                encoding="utf-8",
            )

            missing_project = run_cli(
                "record", "--workflow", str(workflow), "--kind", "evidence",
                "--record", str(record), env=env,
            )
            registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "evidence",
                "--record", str(record), "--project", str(project), env=env,
            )

            self.assertEqual(missing_project.returncode, 2)
            self.assertEqual(registered.returncode, 0, registered.stdout)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["evidence"][0]["id"], "EVD-001")
            self.assertEqual(updated["git_baseline"], state_payload["git_baseline"])

            other_project = base / "other-project"
            other_project.mkdir()
            cross_project = run_cli(
                "record", "--workflow", str(workflow), "--kind", "evidence",
                "--record", str(record), "--project", str(other_project), env=env,
            )
            self.assertEqual(cross_project.returncode, 2)
            self.assertIn(
                "does not own",
                json.loads(cross_project.stdout)["error"]["message"],
            )

    def test_task_registration_requires_self_contained_handoff_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._workflow(Path(directory))
            record = workflow / "系统" / "task-record.yaml"
            record.write_text(
                json.dumps({
                    "id": "TASK-001",
                    "status": "pending",
                    "currentness": "current",
                    "depends_on": [],
                }),
                encoding="utf-8",
            )

            result = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(record), env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("task blockers", json.loads(result.stdout)["error"]["message"])

            package = workflow / "过程产物" / "任务交接" / "TASK-001-实施任务.md"
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_text("task package\n", encoding="utf-8")
            startup = workflow / "过程产物" / "任务交接" / "TASK-001-启动提示词.md"
            startup.write_text("read the task package\n", encoding="utf-8")
            report = workflow / "过程产物" / "实施报告" / "TASK-001.md"
            full = {
                "id": "TASK-001",
                "status": "pending",
                "currentness": "current",
                "parallel_group": "serial-1",
                "depends_on": [],
                "blockers": [],
                "trace_ids": ["REQ-001", "DEC-001"],
                "acceptance_ids": ["REQ-001"],
                "allowed_paths": ["src"],
                "forbidden_paths": ["secrets"],
                "write_paths": ["src"],
                "shared_contracts": [],
                "migrations": [],
                "generated_files": [],
                "git_baseline": json.loads(
                    (workflow / "系统" / "state.yaml").read_text(encoding="utf-8")
                )["git_baseline"],
                "worktree": str(Path(directory) / "worktree"),
                "branch": "task/TASK-001",
                "task_package_path": str(package),
                "startup_prompt_path": str(startup),
                "output_path": str(report),
            }
            record.write_text(json.dumps(full), encoding="utf-8")
            missing_review = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(record), env=env,
            )
            forged_review = dict(full)
            forged_review.update(
                {
                    "review_required": True,
                    "review_history": [],
                    "review": {
                        "status": "recorded",
                        "baseline": full["git_baseline"],
                        "goals_satisfied": True,
                        "test_evidence_satisfied": True,
                        "unresolved_route_issue": False,
                        "comments": [],
                    },
                }
            )
            record.write_text(json.dumps(forged_review), encoding="utf-8")
            forged_recorded_review = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(record), env=env,
            )
            full.update(
                {
                    "review_required": True,
                    "review_history": [],
                    "review": {
                        "status": "pending",
                        "goals_satisfied": False,
                        "test_evidence_satisfied": False,
                        "unresolved_route_issue": False,
                        "comments": [],
                    },
                }
            )
            record.write_text(json.dumps(full), encoding="utf-8")
            registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(record), env=env,
            )
            started = run_cli(
                "task-transition", "--workflow", str(workflow),
                "--task", "TASK-001", "--to", "in_progress",
                "--project", str(Path(directory) / "project"), env=env,
            )
            no_evidence = run_cli(
                "task-transition", "--workflow", str(workflow),
                "--task", "TASK-001", "--to", "completed",
                "--project", str(Path(directory) / "project"), env=env,
            )
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("implementation report\n", encoding="utf-8")
            evidence_output = workflow / "过程产物" / "实施报告" / "other.log"
            evidence_output.write_text("ok\n", encoding="utf-8")
            evidence_record = workflow / "系统" / "other-evidence.yaml"
            evidence_record.write_text(
                json.dumps({
                    "id": "EVD-OTHER",
                    "status": "valid",
                    "currentness": "current",
                    "command": "python3 -m unittest",
                    "working_directory": str(Path(directory) / "project"),
                    "exit_code": 0,
                    "baseline": full["git_baseline"],
                    "producer": "verifier",
                    "reproducible": True,
                    "requirements": ["REQ-001"],
                    "decisions": [],
                    "tasks": ["TASK-OTHER"],
                    "issues": [],
                    "executed_at": "2026-07-12T08:00:00+08:00",
                    "validated_at": "2026-07-12T08:01:00+08:00",
                    "expires_at": "2099-07-12T08:01:00+08:00",
                    "output_path": str(evidence_output),
                }),
                encoding="utf-8",
            )
            evidence_registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "evidence",
                "--record", str(evidence_record),
                "--project", str(Path(directory) / "project"), env=env,
            )
            unrelated_evidence = run_cli(
                "task-transition", "--workflow", str(workflow),
                "--task", "TASK-001", "--to", "completed",
                "--evidence", "EVD-OTHER",
                "--project", str(Path(directory) / "project"), env=env,
            )
            linked_record = dict(json.loads(evidence_record.read_text(encoding="utf-8")))
            linked_record.update(
                {
                    "id": "EVD-001",
                    "tasks": ["TASK-001"],
                    "issues": ["ISSUE-MUST"],
                }
            )
            evidence_record.write_text(json.dumps(linked_record), encoding="utf-8")
            linked_registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "evidence",
                "--record", str(evidence_record),
                "--project", str(Path(directory) / "project"), env=env,
            )
            (Path(directory) / "project" / "README.md").write_text(
                "changed after evidence\n", encoding="utf-8"
            )
            stale_completion = run_cli(
                "task-transition", "--workflow", str(workflow),
                "--task", "TASK-001", "--to", "completed",
                "--evidence", "EVD-001",
                "--project", str(Path(directory) / "project"), env=env,
            )
            (Path(directory) / "project" / "README.md").write_text(
                "fixture\n", encoding="utf-8"
            )
            state_path = workflow / "系统" / "state.yaml"
            tasks_path = workflow / "系统" / "tasks.yaml"
            legacy_state = json.loads(state_path.read_text(encoding="utf-8"))
            legacy_task = next(
                item for item in legacy_state["tasks"] if item["id"] == "TASK-001"
            )
            legacy_task.pop("review_required", None)
            legacy_task.pop("review", None)
            state_path.write_text(json.dumps(legacy_state), encoding="utf-8")
            tasks_payload = json.loads(tasks_path.read_text(encoding="utf-8"))
            tasks_payload["tasks"] = legacy_state["tasks"]
            tasks_path.write_text(json.dumps(tasks_payload), encoding="utf-8")
            legacy_completion = run_cli(
                "task-transition", "--workflow", str(workflow),
                "--task", "TASK-001", "--to", "completed",
                "--evidence", "EVD-001",
                "--project", str(Path(directory) / "project"), env=env,
            )
            review_path = workflow / "系统" / "task-review.yaml"
            review_path.write_text(
                json.dumps(
                    {
                        "status": "recorded",
                        "goals_satisfied": True,
                        "test_evidence_satisfied": True,
                        "unresolved_route_issue": False,
                        "comments": [
                            {
                                "id": "ISSUE-MUST",
                                "classification": "must_fix",
                                "status": "open",
                                "evidence": [],
                            },
                            {
                                "id": "ISSUE-OPTIONAL",
                                "classification": "optional_optimization",
                                "status": "open",
                                "evidence": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            review_recorded = run_cli(
                "task-review", "--workflow", str(workflow),
                "--task", "TASK-001", "--review", str(review_path),
                "--project", str(Path(directory) / "project"), env=env,
            )
            bad_review_completion = run_cli(
                "task-transition", "--workflow", str(workflow),
                "--task", "TASK-001", "--to", "completed",
                "--evidence", "EVD-001",
                "--project", str(Path(directory) / "project"), env=env,
            )
            corrected_review = json.loads(review_path.read_text(encoding="utf-8"))
            deletion_review = dict(corrected_review)
            deletion_review["comments"] = [corrected_review["comments"][1]]
            review_path.write_text(json.dumps(deletion_review), encoding="utf-8")
            deleted_must_fix = run_cli(
                "task-review", "--workflow", str(workflow),
                "--task", "TASK-001", "--review", str(review_path),
                "--project", str(Path(directory) / "project"), env=env,
            )
            downgraded_review = json.loads(
                json.dumps(corrected_review)
            )
            downgraded_review["comments"][0]["classification"] = "optional_optimization"
            review_path.write_text(json.dumps(downgraded_review), encoding="utf-8")
            downgraded_must_fix = run_cli(
                "task-review", "--workflow", str(workflow),
                "--task", "TASK-001", "--review", str(review_path),
                "--project", str(Path(directory) / "project"), env=env,
            )
            corrected_review["comments"][0]["status"] = "fixed"
            corrected_review["comments"][0]["evidence"] = ["EVD-001"]
            review_path.write_text(json.dumps(corrected_review), encoding="utf-8")
            review_corrected = run_cli(
                "task-review", "--workflow", str(workflow),
                "--task", "TASK-001", "--review", str(review_path),
                "--project", str(Path(directory) / "project"), env=env,
            )
            completed = run_cli(
                "task-transition", "--workflow", str(workflow),
                "--task", "TASK-001", "--to", "completed",
                "--evidence", "EVD-001",
                "--project", str(Path(directory) / "project"), env=env,
            )

            self.assertEqual(missing_review.returncode, 2, missing_review.stdout)
            self.assertIn(
                "review_required",
                json.loads(missing_review.stdout)["error"]["message"],
            )
            self.assertEqual(
                forged_recorded_review.returncode, 2, forged_recorded_review.stdout
            )
            self.assertIn(
                "pending",
                json.loads(forged_recorded_review.stdout)["error"]["message"],
            )
            self.assertEqual(registered.returncode, 0, registered.stdout)
            self.assertEqual(started.returncode, 0, started.stdout)
            self.assertEqual(no_evidence.returncode, 2)
            self.assertIn(
                "requires evidence",
                json.loads(no_evidence.stdout)["error"]["message"],
            )
            self.assertEqual(evidence_registered.returncode, 0, evidence_registered.stdout)
            self.assertEqual(unrelated_evidence.returncode, 2)
            self.assertIn(
                "does not trace",
                json.loads(unrelated_evidence.stdout)["error"]["message"],
            )
            self.assertEqual(linked_registered.returncode, 0, linked_registered.stdout)
            self.assertEqual(stale_completion.returncode, 2)
            self.assertIn(
                "Git 基线",
                json.loads(stale_completion.stdout)["error"]["message"],
            )
            self.assertEqual(review_recorded.returncode, 0, review_recorded.stdout)
            self.assertEqual(legacy_completion.returncode, 2, legacy_completion.stdout)
            self.assertIn(
                "review_required",
                json.loads(legacy_completion.stdout)["error"]["message"],
            )
            self.assertEqual(bad_review_completion.returncode, 2, bad_review_completion.stdout)
            self.assertIn(
                "ISSUE-MUST",
                json.loads(bad_review_completion.stdout)["error"]["message"],
            )
            self.assertEqual(deleted_must_fix.returncode, 2, deleted_must_fix.stdout)
            self.assertEqual(downgraded_must_fix.returncode, 2, downgraded_must_fix.stdout)
            self.assertEqual(review_corrected.returncode, 0, review_corrected.stdout)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            completed_state = json.loads(
                (workflow / "系统" / "state.yaml").read_text(encoding="utf-8")
            )
            completed_task = next(
                item for item in completed_state["tasks"] if item["id"] == "TASK-001"
            )
            self.assertTrue(completed_task["review_convergence"]["completion_allowed"])
            self.assertEqual(
                completed_task["review_convergence"]["optional_review_ids"],
                ["ISSUE-OPTIONAL"],
            )

    def test_dirty_git_worktree_invalidates_clean_baseline_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env, workflow = self._workflow(base)
            state_payload = json.loads(
                (workflow / "系统" / "state.yaml").read_text(encoding="utf-8")
            )
            project = base / "project"
            (project / "README.md").write_text("dirty\n", encoding="utf-8")
            output = workflow / "过程产物" / "实施报告" / "dirty.log"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok\n", encoding="utf-8")
            record = workflow / "系统" / "dirty-evidence.yaml"
            record.write_text(
                json.dumps({
                    "id": "EVD-DIRTY",
                    "status": "valid",
                    "currentness": "current",
                    "command": "test",
                    "working_directory": str(project),
                    "exit_code": 0,
                    "baseline": state_payload["git_baseline"],
                    "producer": "verifier",
                    "reproducible": True,
                    "requirements": ["REQ-001"],
                    "decisions": [],
                    "tasks": [],
                    "issues": [],
                    "executed_at": "2026-07-12T08:00:00+08:00",
                    "validated_at": "2026-07-12T08:01:00+08:00",
                    "expires_at": "2099-07-12T08:01:00+08:00",
                    "output_path": str(output),
                }),
                encoding="utf-8",
            )

            result = run_cli(
                "record", "--workflow", str(workflow), "--kind", "evidence",
                "--record", str(record), "--project", str(project), env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "Git 基线",
                json.loads(result.stdout)["error"]["message"],
            )

    def test_dirty_baseline_changes_when_modified_file_content_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _, _ = self._workflow(base)
            project = base / "project"
            identity = state.identify_project(project)
            target = project / "README.md"
            target.write_text("change-one\n", encoding="utf-8")
            first = grh._current_baseline(project, identity)
            target.write_text("change-two\n", encoding="utf-8")
            second = grh._current_baseline(project, identity)

            self.assertNotEqual(first, second)

    def test_cancelled_required_phase_does_not_satisfy_phase_order(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._workflow(Path(directory))

            cancelled = run_cli(
                "transition", "--workflow", str(workflow),
                "--phase", "preflight", "--to", "cancelled", env=env,
            )
            next_phase = run_cli(
                "transition", "--workflow", str(workflow),
                "--phase", "alignment", "--to", "in_progress", env=env,
            )

            self.assertEqual(cancelled.returncode, 0, cancelled.stdout)
            self.assertEqual(next_phase.returncode, 2)
            self.assertIn(
                "previous phases",
                json.loads(next_phase.stdout)["error"]["message"],
            )

    def test_required_phase_cannot_be_relabelled_optional_and_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._workflow(Path(directory))

            result = run_cli(
                "transition", "--workflow", str(workflow),
                "--phase", "preflight", "--to", "skipped",
                "--skip-reason", "try to bypass",
                "--skip-approval-id", "DEC-999", env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "cannot be changed to optional",
                json.loads(result.stdout)["error"]["message"],
            )

    def test_failure_record_atomically_persists_same_issue_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env, workflow = self._workflow(base)
            state_path = workflow / "系统" / "state.yaml"

            results = [
                run_cli(
                    "failure-record",
                    "--workflow",
                    str(workflow),
                    "--project",
                    str(base / "project"),
                    "--failure-class",
                    "implementation_failure",
                    "--issue-id",
                    "ISSUE-007",
                    "--failed-acceptance",
                    "REQ-004",
                    "--evidence",
                    "EVD-007",
                    env=env,
                )
                for _ in range(3)
            ]

            self.assertEqual(
                [result.returncode for result in results],
                [0, 0, 0],
                [result.stdout for result in results],
            )
            payloads = [json.loads(result.stdout)["failure"] for result in results]
            self.assertEqual(
                [item["action"] for item in payloads],
                ["minimal_fix", "root_cause_recheck", "recover_required"],
            )
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted["failure_attempts"]), 3)
            self.assertEqual(
                [item["attempt_count"] for item in persisted["failure_attempts"]],
                [1, 2, 3],
            )
            failure_manifest = json.loads(
                (workflow / "系统" / "failures.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(failure_manifest["failure_attempts"], persisted["failure_attempts"])
            self.assertEqual(failure_manifest["count"], 3)
            self.assertEqual(
                failure_manifest["head"], persisted["failure_attempts"][-1]["record_hash"]
            )
            self.assertTrue(
                failure_control.validate_failure_chain(
                    persisted["failure_attempts"],
                    failure_manifest,
                    ledger=persisted["ledger"],
                )["valid"]
            )
            package = workflow / "过程产物" / "审查修复" / "TASK-REPAIR-修复任务.md"
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_text("repair package\n", encoding="utf-8")
            startup = workflow / "过程产物" / "审查修复" / "TASK-REPAIR-启动提示词.md"
            startup.write_text("read repair package\n", encoding="utf-8")
            output = workflow / "过程产物" / "审查修复" / "TASK-REPAIR-报告.md"
            task_record = workflow / "系统" / "repair-task.yaml"
            task_record.write_text(
                json.dumps(
                    {
                        "id": "TASK-REPAIR",
                        "task_type": "repair",
                        "repair_mode": "ordinary",
                        "review_required": True,
                        "review_history": [],
                        "review": {
                            "status": "pending",
                            "goals_satisfied": False,
                            "test_evidence_satisfied": False,
                            "unresolved_route_issue": False,
                            "comments": [],
                        },
                        "failure_class": "implementation_failure",
                        "failure_fingerprint": payloads[-1]["fingerprint"],
                        "attempt_count": 3,
                        "status": "pending",
                        "currentness": "current",
                        "parallel_group": "serial-repair",
                        "depends_on": [],
                        "blockers": [],
                        "trace_ids": ["REQ-004", "ISSUE-007"],
                        "acceptance_ids": ["REQ-004"],
                        "allowed_paths": ["src"],
                        "forbidden_paths": ["secrets"],
                        "write_paths": ["src"],
                        "shared_contracts": [],
                        "migrations": [],
                        "generated_files": [],
                        "git_baseline": persisted["git_baseline"],
                        "worktree": str(base / "worktree"),
                        "branch": "repair/TASK-REPAIR",
                        "task_package_path": str(package),
                        "startup_prompt_path": str(startup),
                        "output_path": str(output),
                    }
                ),
                encoding="utf-8",
            )

            repair = run_cli(
                "record",
                "--workflow",
                str(workflow),
                "--kind",
                "task",
                "--record",
                str(task_record),
                env=env,
            )

            self.assertEqual(repair.returncode, 2, repair.stdout)
            self.assertIn("grh-recover", json.loads(repair.stdout)["error"]["message"])

            privileged_task = json.loads(task_record.read_text(encoding="utf-8"))
            privileged_task.pop("repair_mode")
            task_record.write_text(json.dumps(privileged_task), encoding="utf-8")
            missing_mode = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(task_record), env=env,
            )
            privileged_task["repair_mode"] = "unknown_escape"
            task_record.write_text(json.dumps(privileged_task), encoding="utf-8")
            unknown_mode = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(task_record), env=env,
            )
            privileged_task["repair_mode"] = "recovery"
            task_record.write_text(json.dumps(privileged_task), encoding="utf-8")
            missing_approval = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(task_record), env=env,
            )

            self.assertEqual(missing_mode.returncode, 2, missing_mode.stdout)
            self.assertIn("repair_mode", json.loads(missing_mode.stdout)["error"]["message"])
            self.assertEqual(unknown_mode.returncode, 2, unknown_mode.stdout)
            self.assertIn("repair_mode", json.loads(unknown_mode.stdout)["error"]["message"])
            self.assertEqual(missing_approval.returncode, 2, missing_approval.stdout)
            self.assertIn("approval", json.loads(missing_approval.stdout)["error"]["message"])

            recovery_approval = workflow / "系统" / "recovery-approval.yaml"
            recovery_approval.write_text(
                json.dumps(
                    {
                        "id": "DEC-777",
                        "type": "DEC",
                        "version": 1,
                        "status": "approved",
                        "approved_by": "user",
                        "gate": "failure_recovery",
                        "repair_mode": "recovery",
                        "failure_fingerprint": payloads[-1]["fingerprint"],
                        "issue_id": "ISSUE-007",
                        "reason": "用户批准第三轮后进入恢复任务",
                    }
                ),
                encoding="utf-8",
            )
            approval_registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "ledger",
                "--record", str(recovery_approval), env=env,
            )
            privileged_task["repair_approval_id"] = "DEC-777"
            privileged_task["repair_approval_version"] = 1
            privileged_task["repair_approval_hash"] = (
                failure_control.approval_record_hash(
                    json.loads(recovery_approval.read_text(encoding="utf-8"))
                )
            )
            task_record.write_text(json.dumps(privileged_task), encoding="utf-8")
            authorized_recovery = run_cli(
                "record", "--workflow", str(workflow), "--kind", "task",
                "--record", str(task_record), env=env,
            )

            self.assertEqual(approval_registered.returncode, 0, approval_registered.stdout)
            self.assertEqual(authorized_recovery.returncode, 0, authorized_recovery.stdout)

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            persisted["failure_attempts"][-1].update(
                {
                    "attempt_count": 1,
                    "action": "minimal_fix",
                    "ordinary_repair_allowed": True,
                }
            )
            state_path.write_text(json.dumps(persisted), encoding="utf-8")
            reconciled_tamper = run_cli(
                "reconcile", "--workflow", str(workflow),
                "--project", str(base / "project"), env=env,
            )
            tampered_task = json.loads(task_record.read_text(encoding="utf-8"))
            tampered_task.update({"id": "TASK-TAMPER", "attempt_count": 2})
            task_record.write_text(json.dumps(tampered_task), encoding="utf-8")

            tampered = run_cli(
                "record",
                "--workflow",
                str(workflow),
                "--kind",
                "task",
                "--record",
                str(task_record),
                env=env,
            )

            self.assertEqual(tampered.returncode, 2, tampered.stdout)
            self.assertEqual(reconciled_tamper.returncode, 1, reconciled_tamper.stdout)
            self.assertIn(
                "FAILURE_MANIFEST_DIVERGENCE",
                {
                    item["code"]
                    for item in json.loads(reconciled_tamper.stdout)["reconciliation"]["conflicts"]
                },
            )
            self.assertIn(
                "failure_attempts manifest",
                json.loads(tampered.stdout)["error"]["message"],
            )

    def test_failure_threshold_override_uses_persisted_user_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env, workflow = self._workflow(base)
            state_path = workflow / "系统" / "state.yaml"
            origin = json.loads(state_path.read_text(encoding="utf-8"))["git_baseline"]
            fingerprint = failure_control.issue_fingerprint(
                {
                    "issue_id": "ISSUE-401",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": origin,
                }
            )
            approval = workflow / "系统" / "failure-threshold-decision.yaml"
            approval.write_text(
                json.dumps(
                    {
                        "id": "DEC-401",
                        "type": "DEC",
                        "version": 1,
                        "summary": "用户批准把同问题阈值提高到四轮",
                        "status": "approved",
                        "approved_by": "user",
                        "failure_fingerprint": fingerprint,
                        "issue_id": "ISSUE-401",
                        "approved_threshold": 4,
                        "reason": "用户要求用第四轮验证新根因",
                    }
                ),
                encoding="utf-8",
            )
            registered = run_cli(
                "record",
                "--workflow",
                str(workflow),
                "--kind",
                "ledger",
                "--record",
                str(approval),
                env=env,
            )
            before_invalid = state_path.read_text(encoding="utf-8")
            common_arguments = (
                "failure-record",
                "--workflow",
                str(workflow),
                "--project",
                str(base / "project"),
                "--failure-class",
                "implementation_failure",
                "--issue-id",
                "ISSUE-401",
                "--failed-command",
                "python3 -m unittest",
                "--threshold",
                "4",
                "--override-reason",
                "用户要求用第四轮验证新根因",
            )

            invalid = run_cli(
                *common_arguments, "--approval-id", "DEC-404", env=env
            )
            after_invalid = state_path.read_text(encoding="utf-8")
            valid = [
                run_cli(
                    *common_arguments, "--approval-id", "DEC-401", env=env
                )
                for _ in range(4)
            ]

            self.assertEqual(registered.returncode, 0, registered.stdout)
            self.assertEqual(invalid.returncode, 2, invalid.stdout)
            self.assertEqual(after_invalid, before_invalid)
            self.assertEqual([item.returncode for item in valid], [0, 0, 0, 0])
            actions = [json.loads(item.stdout)["failure"]["action"] for item in valid]
            self.assertEqual(
                actions,
                [
                    "minimal_fix",
                    "root_cause_recheck",
                    "root_cause_recheck",
                    "recover_required",
                ],
            )

    def test_failure_record_reuses_existing_chain_after_current_baseline_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env, workflow = self._workflow(base)
            project = base / "project"
            common_arguments = (
                "failure-record",
                "--workflow",
                str(workflow),
                "--project",
                str(project),
                "--failure-class",
                "implementation_failure",
                "--issue-id",
                "ISSUE-501",
                "--failed-acceptance",
                "REQ-501",
            )

            first = run_cli(*common_arguments, env=env)
            first_payload = json.loads(first.stdout)["failure"]
            (project / "README.md").write_text("repair changed baseline\n", encoding="utf-8")
            second = run_cli(
                *common_arguments,
                env=env,
            )

            self.assertEqual(first.returncode, 0, first.stdout)
            self.assertEqual(second.returncode, 0, second.stdout)
            second_payload = json.loads(second.stdout)["failure"]
            self.assertEqual(second_payload["fingerprint"], first_payload["fingerprint"])
            self.assertEqual(second_payload["attempt_count"], 2)
            self.assertEqual(
                second_payload["record"]["originating_baseline"],
                first_payload["record"]["originating_baseline"],
            )
            self.assertNotEqual(
                second_payload["record"]["current_baseline"],
                first_payload["record"]["current_baseline"],
            )

            (project / "README.md").write_text(
                "second repair changed baseline\n", encoding="utf-8"
            )
            wrong_fingerprint = run_cli(
                *common_arguments,
                "--existing-fingerprint",
                "FAIL-0000000000000000",
                env=env,
            )
            unapproved_new_chain = run_cli(
                *common_arguments,
                "--new-chain",
                "--new-chain-reason",
                "用户确认原修复链不再适用",
                env=env,
            )
            current_baseline = grh._current_baseline(
                project, state.identify_project(project)
            )
            new_fingerprint = failure_control.issue_fingerprint(
                {
                    "issue_id": "ISSUE-501",
                    "failed_acceptance": ["REQ-501"],
                    "failed_command": [],
                    "originating_baseline": current_baseline,
                }
            )
            approval = workflow / "系统" / "new-chain-approval.yaml"
            approval.write_text(
                json.dumps(
                    {
                        "id": "DEC-501",
                        "type": "DEC",
                        "version": 1,
                        "status": "approved",
                        "approved_by": "user",
                        "gate": "new_failure_chain",
                        "failure_fingerprint": new_fingerprint,
                        "issue_id": "ISSUE-501",
                        "failure_class": "implementation_failure",
                        "originating_baseline": current_baseline,
                        "reason": "用户确认原修复链不再适用",
                    }
                ),
                encoding="utf-8",
            )
            approval_registered = run_cli(
                "record", "--workflow", str(workflow), "--kind", "ledger",
                "--record", str(approval), env=env,
            )
            approved_new_chain = run_cli(
                *common_arguments,
                "--new-chain",
                "--new-chain-approval-id",
                "DEC-501",
                "--new-chain-reason",
                "用户确认原修复链不再适用",
                env=env,
            )

            self.assertEqual(wrong_fingerprint.returncode, 2, wrong_fingerprint.stdout)
            self.assertEqual(unapproved_new_chain.returncode, 2, unapproved_new_chain.stdout)
            self.assertEqual(approval_registered.returncode, 0, approval_registered.stdout)
            self.assertEqual(approved_new_chain.returncode, 0, approved_new_chain.stdout)
            approved_payload = json.loads(approved_new_chain.stdout)["failure"]
            self.assertEqual(approved_payload["fingerprint"], new_fingerprint)
            self.assertEqual(approved_payload["attempt_count"], 1)

    def test_concurrent_failure_records_keep_every_unique_attempt_number(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env, workflow = self._workflow(base)
            arguments = (
                "failure-record",
                "--workflow",
                str(workflow),
                "--project",
                str(base / "project"),
                "--failure-class",
                "implementation_failure",
                "--issue-id",
                "ISSUE-777",
                "--failed-acceptance",
                "REQ-777",
            )

            with ThreadPoolExecutor(max_workers=6) as executor:
                results = list(
                    executor.map(
                        lambda _: run_cli(*arguments, env=env),
                        range(6),
                    )
                )

            self.assertEqual([item.returncode for item in results], [0] * 6)
            persisted = json.loads(
                (workflow / "系统" / "state.yaml").read_text(encoding="utf-8")
            )["failure_attempts"]
            self.assertEqual(len(persisted), 6)
            self.assertEqual(
                sorted(item["attempt_count"] for item in persisted),
                [1, 2, 3, 4, 5, 6],
            )
            self.assertEqual(len({item["fingerprint"] for item in persisted}), 1)

    def test_failure_record_rolls_back_all_files_after_post_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            env, workflow = self._workflow(base)
            state_path = workflow / "系统" / "state.yaml"
            baseline = json.loads(state_path.read_text(encoding="utf-8"))["git_baseline"]
            tracked = [
                state_path,
                workflow / "系统" / "artifacts.yaml",
                workflow / "系统" / "tasks.yaml",
                workflow / "系统" / "evidence.yaml",
                workflow / "系统" / "failures.yaml",
            ]
            before = {path: path.read_bytes() for path in tracked}
            original_unlink = Path.unlink
            failed = {"value": False}

            def fail_first_journal_unlink(path, *args, **kwargs):
                if (
                    path.name == workflow_ops.TRANSACTION_FILE
                    and not failed["value"]
                ):
                    failed["value"] = True
                    raise OSError("simulated post-replace failure")
                return original_unlink(path, *args, **kwargs)

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(Path, "unlink", fail_first_journal_unlink):
                    with self.assertRaisesRegex(OSError, "post-replace"):
                        workflow_ops.record_failure_attempt(
                            workflow,
                            {
                                "failure_class": "implementation_failure",
                                "issue_id": "ISSUE-778",
                                "failed_acceptance": ["REQ-778"],
                            },
                            current_baseline=baseline,
                        )

            after = {path: path.read_bytes() for path in tracked}
            self.assertEqual(after, before)
            self.assertFalse(
                (workflow / "系统" / workflow_ops.TRANSACTION_FILE).exists()
            )


if __name__ == "__main__":
    unittest.main()
