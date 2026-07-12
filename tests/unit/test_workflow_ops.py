import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "grill-harness" / "scripts" / "grh.py"
SCRIPTS = CLI.parent
sys.path.insert(0, str(SCRIPTS))

import grh
import state


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
            linked_record.update({"id": "EVD-001", "tasks": ["TASK-001"]})
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


if __name__ == "__main__":
    unittest.main()
