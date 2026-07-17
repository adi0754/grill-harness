import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import failure_control
import workflow_ops


CLI = ROOT / "skills" / "grill-harness" / "scripts" / "grh.py"


def run_cli(*arguments, env=None):
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        capture_output=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


class MigrationTests(unittest.TestCase):
    def _yaml_snapshot(self, workflow):
        return {
            path.relative_to(workflow): path.read_bytes()
            for path in workflow.rglob("*.yaml")
        }

    def _legacy_workflow(self, base):
        root = base / "storage"
        project = base / "project"
        project.mkdir()
        env = dict(os.environ)
        env["GRILL_HARNESS_TEST_ROOT"] = str(root)
        created = run_cli(
            "init", "--project", str(project), "--workflow-name", "迁移检查",
            "--workflow-key", "migration", "--created-date", "2026-07-12", env=env,
        )
        workflow = Path(json.loads(created.stdout)["workflow_path"])
        for filename in ("state.yaml", "artifacts.yaml", "tasks.yaml", "evidence.yaml"):
            path = workflow / "系统" / filename
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.pop("workflow_version", None)
            if filename != "state.yaml":
                payload.pop("schema_version", None)
            payload["future_unknown"] = {"keep": True}
            path.write_text(json.dumps(payload), encoding="utf-8")
        (workflow / "系统" / "failures.yaml").unlink()
        return env, workflow

    def test_migration_backs_up_preserves_unknown_fields_and_can_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))

            migrated = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(migrated.returncode, 0, migrated.stdout)
            payload = json.loads(migrated.stdout)
            self.assertTrue(payload["migration"]["changed"])
            report_path = Path(payload["migration"]["report_path"])
            self.assertTrue(report_path.is_file())
            state_payload = json.loads(
                (workflow / "系统" / "state.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(state_payload["workflow_version"], 1)
            self.assertEqual(state_payload["future_unknown"], {"keep": True})
            failure_manifest = json.loads(
                (workflow / "系统" / "failures.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(failure_manifest["integrity_origin"], "migration")
            self.assertEqual(failure_manifest["count"], 0)

            rolled_back = run_cli(
                "rollback", "--report", str(report_path), env=env
            )

            self.assertEqual(rolled_back.returncode, 0, rolled_back.stdout)
            restored = json.loads(
                (workflow / "系统" / "state.yaml").read_text(encoding="utf-8")
            )
            self.assertNotIn("workflow_version", restored)
            self.assertEqual(restored["future_unknown"], {"keep": True})
            self.assertFalse((workflow / "系统" / "failures.yaml").exists())

    def test_migration_refuses_divergent_manifests_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            tasks = workflow / "系统" / "tasks.yaml"
            payload = json.loads(tasks.read_text(encoding="utf-8"))
            payload["tasks"] = [{"id": "TASK-X"}]
            tasks.write_text(json.dumps(payload), encoding="utf-8")
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                self._yaml_snapshot(workflow), before
            )

    def test_migration_snapshots_the_unique_historical_threshold_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            fingerprint = failure_control.issue_fingerprint(
                {
                    "issue_id": "ISSUE-701",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": state_payload["git_baseline"],
                }
            )
            approval_v1 = {
                "id": "DEC-701",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-701",
                "approved_threshold": 4,
                "reason": "legacy threshold",
            }
            approval_v2 = dict(
                approval_v1,
                version=2,
                approved_threshold=5,
                reason="later different approval",
            )
            attempt = failure_control.record_attempt(
                [],
                {
                    "failure_class": "implementation_failure",
                    "issue_id": "ISSUE-701",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": state_payload["git_baseline"],
                    "current_baseline": state_payload["git_baseline"],
                },
                threshold_override={
                    "threshold": 4,
                    "approval_id": "DEC-701",
                    "reason": "legacy threshold",
                },
                ledger=[approval_v1],
            )["record"]
            attempt["threshold_override"].pop("approval_version")
            attempt["threshold_override"].pop("approval_hash")
            state_payload["ledger"] = [approval_v1, approval_v2]
            state_payload["failure_attempts"] = [attempt]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")

            migrated = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(migrated.returncode, 0, migrated.stdout)
            migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
            snapshot = migrated_state["failure_attempts"][0]["threshold_override"]
            self.assertEqual(snapshot["approval_version"], 1)
            self.assertEqual(
                snapshot["approval_hash"],
                failure_control.approval_record_hash(approval_v1),
            )
            manifest = json.loads(
                (workflow / "系统" / "failures.yaml").read_text(encoding="utf-8")
            )
            self.assertTrue(
                failure_control.validate_failure_chain(
                    migrated_state["failure_attempts"],
                    manifest,
                    ledger=migrated_state["ledger"],
                )["valid"]
            )

    def test_migration_hydrates_mirrored_legacy_failure_records(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            facts = {
                "failure_class": "implementation_failure",
                "issue_id": "ISSUE-707",
                "failed_command": ["python3 -m unittest"],
                "failed_acceptance": [],
                "originating_baseline": state_payload["git_baseline"],
                "current_baseline": state_payload["git_baseline"],
            }
            fingerprint = failure_control.issue_fingerprint(facts)
            approval = {
                "id": "DEC-707",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-707",
                "approved_threshold": 4,
                "reason": "legacy threshold",
            }
            attempt = failure_control.record_attempt(
                [],
                facts,
                threshold_override={
                    "threshold": 4,
                    "approval_id": "DEC-707",
                    "reason": "legacy threshold",
                },
                ledger=[approval],
            )["record"]
            attempt["threshold_override"].pop("approval_version")
            attempt["threshold_override"].pop("approval_hash")
            sealed = failure_control.seal_failure_record(attempt, None)
            state_payload["ledger"] = [approval]
            state_payload["failure_attempts"] = [sealed]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")
            manifest = failure_control.failure_chain_manifest(
                [sealed], integrity_origin="migration"
            )
            manifest["schema_version"] = 0
            manifest["workflow_version"] = 0
            failures_path = workflow / "系统" / "failures.yaml"
            failures_path.write_text(json.dumps(manifest), encoding="utf-8")

            migrated = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(migrated.returncode, 0, migrated.stdout)
            migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
            migrated_manifest = json.loads(failures_path.read_text(encoding="utf-8"))
            self.assertNotIn("_migration_hydration_changed", migrated_state)
            self.assertEqual(
                migrated_state["failure_attempts"],
                migrated_manifest["failure_attempts"],
            )
            snapshot = migrated_state["failure_attempts"][0]["threshold_override"]
            self.assertEqual(snapshot["approval_version"], 1)
            self.assertEqual(
                snapshot["approval_hash"],
                failure_control.approval_record_hash(approval),
            )

    def test_migration_writes_hydrated_snapshots_for_a_version_one_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            created = run_cli(
                "init",
                "--project",
                str(project),
                "--workflow-name",
                "真实升级",
                "--workflow-key",
                "real-upgrade",
                "--created-date",
                "2026-07-12",
                env=env,
            )
            workflow = Path(json.loads(created.stdout)["workflow_path"])
            state_path = workflow / "系统" / "state.yaml"
            failures_path = workflow / "系统" / "failures.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            facts = {
                "failure_class": "implementation_failure",
                "issue_id": "ISSUE-708",
                "failed_command": ["python3 -m unittest"],
                "failed_acceptance": [],
                "originating_baseline": state_payload["git_baseline"],
                "current_baseline": state_payload["git_baseline"],
            }
            fingerprint = failure_control.issue_fingerprint(facts)
            approval = {
                "id": "DEC-708",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-708",
                "approved_threshold": 4,
                "reason": "legacy threshold",
            }
            attempt = failure_control.record_attempt(
                [],
                facts,
                threshold_override={
                    "threshold": 4,
                    "approval_id": "DEC-708",
                    "reason": "legacy threshold",
                },
                ledger=[approval],
            )["record"]
            attempt["threshold_override"].pop("approval_version")
            attempt["threshold_override"].pop("approval_hash")
            sealed = failure_control.seal_failure_record(attempt, None)
            state_payload["ledger"] = [approval]
            state_payload["failure_attempts"] = [sealed]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")
            manifest = failure_control.failure_chain_manifest([sealed])
            failures_path.write_text(json.dumps(manifest), encoding="utf-8")

            migrated = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(migrated.returncode, 0, migrated.stdout)
            self.assertTrue(json.loads(migrated.stdout)["migration"]["changed"])
            migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
            migrated_manifest = json.loads(failures_path.read_text(encoding="utf-8"))
            self.assertNotIn("_migration_hydration_changed", migrated_state)
            self.assertEqual(
                migrated_state["failure_attempts"],
                migrated_manifest["failure_attempts"],
            )
            snapshot = migrated_state["failure_attempts"][0]["threshold_override"]
            self.assertEqual(snapshot["approval_version"], 1)
            self.assertEqual(
                snapshot["approval_hash"],
                failure_control.approval_record_hash(approval),
            )

    def test_migration_does_not_reseal_unrelated_current_version_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            created = run_cli(
                "init",
                "--project",
                str(project),
                "--workflow-name",
                "损坏检查",
                "--workflow-key",
                "corruption-check",
                "--created-date",
                "2026-07-12",
                env=env,
            )
            workflow = Path(json.loads(created.stdout)["workflow_path"])
            state_path = workflow / "系统" / "state.yaml"
            failures_path = workflow / "系统" / "failures.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            attempt = failure_control.record_attempt(
                [],
                {
                    "failure_class": "implementation_failure",
                    "issue_id": "ISSUE-709",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": state_payload["git_baseline"],
                    "current_baseline": state_payload["git_baseline"],
                },
            )["record"]
            sealed = failure_control.seal_failure_record(attempt, None)
            sealed["record_hash"] = "0" * 64
            state_payload["failure_attempts"] = [sealed]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")
            manifest = failure_control.failure_chain_manifest([sealed])
            failures_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertEqual(self._yaml_snapshot(workflow), before)

    def test_migration_rejects_a_conflicting_partial_approval_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            facts = {
                "failure_class": "implementation_failure",
                "issue_id": "ISSUE-705",
                "failed_command": ["python3 -m unittest"],
                "failed_acceptance": [],
                "originating_baseline": state_payload["git_baseline"],
                "current_baseline": state_payload["git_baseline"],
            }
            fingerprint = failure_control.issue_fingerprint(facts)
            approval_v1 = {
                "id": "DEC-705",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-705",
                "approved_threshold": 4,
                "reason": "legacy threshold",
            }
            approval_v2 = dict(
                approval_v1,
                version=2,
                approved_threshold=5,
                reason="different later approval",
            )
            attempt = failure_control.record_attempt(
                [],
                facts,
                threshold_override={
                    "threshold": 4,
                    "approval_id": "DEC-705",
                    "reason": "legacy threshold",
                },
                ledger=[approval_v1],
            )["record"]
            attempt["threshold_override"]["approval_version"] = 2
            attempt["threshold_override"].pop("approval_hash")
            state_payload["ledger"] = [approval_v1, approval_v2]
            state_payload["failure_attempts"] = [attempt]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("reconcile", json.loads(result.stdout)["error"]["message"])
            self.assertEqual(self._yaml_snapshot(workflow), before)

    def test_migration_rejects_an_ambiguous_legacy_approval_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            fingerprint = failure_control.issue_fingerprint(
                {
                    "issue_id": "ISSUE-702",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": state_payload["git_baseline"],
                }
            )
            approval_v1 = {
                "id": "DEC-702", "type": "DEC", "version": 1,
                "status": "approved", "approved_by": "user",
                "failure_fingerprint": fingerprint, "issue_id": "ISSUE-702",
                "approved_threshold": 4, "reason": "same approval",
            }
            approval_v2 = dict(approval_v1, version=2)
            attempt = failure_control.record_attempt(
                [],
                {
                    "failure_class": "implementation_failure",
                    "issue_id": "ISSUE-702",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": state_payload["git_baseline"],
                    "current_baseline": state_payload["git_baseline"],
                },
                threshold_override={
                    "threshold": 4, "approval_id": "DEC-702",
                    "reason": "same approval",
                },
                ledger=[approval_v1],
            )["record"]
            attempt["threshold_override"].pop("approval_version")
            attempt["threshold_override"].pop("approval_hash")
            state_payload["ledger"] = [approval_v1, approval_v2]
            state_payload["failure_attempts"] = [attempt]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("reconcile", json.loads(result.stdout)["error"]["message"])
            self.assertEqual(
                self._yaml_snapshot(workflow), before
            )

    def test_migration_snapshots_the_unique_historical_new_chain_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            fingerprint = failure_control.issue_fingerprint(
                {
                    "issue_id": "ISSUE-703",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": state_payload["git_baseline"],
                }
            )
            approval_v1 = {
                "id": "DEC-703",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "gate": "new_failure_chain",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-703",
                "failure_class": "implementation_failure",
                "originating_baseline": state_payload["git_baseline"],
                "reason": "approve legacy chain",
            }
            approval_v2 = dict(
                approval_v1,
                version=2,
                reason="approve a later chain",
            )
            attempt = failure_control.record_attempt(
                [],
                {
                    "failure_class": "implementation_failure",
                    "issue_id": "ISSUE-703",
                    "failed_command": ["python3 -m unittest"],
                    "failed_acceptance": [],
                    "originating_baseline": state_payload["git_baseline"],
                    "current_baseline": state_payload["git_baseline"],
                    "new_chain": True,
                    "new_chain_approval_id": "DEC-703",
                    "new_chain_approval_version": 1,
                    "new_chain_approval_hash": failure_control.approval_record_hash(
                        approval_v1
                    ),
                    "new_chain_reason": "approve legacy chain",
                },
            )["record"]
            attempt["new_chain_approval"].pop("approval_version")
            attempt["new_chain_approval"].pop("approval_hash")
            state_payload["ledger"] = [approval_v1, approval_v2]
            state_payload["failure_attempts"] = [attempt]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")

            migrated = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(migrated.returncode, 0, migrated.stdout)
            migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
            snapshot = migrated_state["failure_attempts"][0]["new_chain_approval"]
            self.assertEqual(snapshot["approval_version"], 1)
            self.assertEqual(
                snapshot["approval_hash"],
                failure_control.approval_record_hash(approval_v1),
            )

    def test_migration_rejects_an_ambiguous_new_chain_approval_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            facts = {
                "failure_class": "implementation_failure",
                "issue_id": "ISSUE-706",
                "failed_command": ["python3 -m unittest"],
                "failed_acceptance": [],
                "originating_baseline": state_payload["git_baseline"],
                "current_baseline": state_payload["git_baseline"],
            }
            fingerprint = failure_control.issue_fingerprint(facts)
            approval_v1 = {
                "id": "DEC-706",
                "type": "DEC",
                "version": 1,
                "status": "approved",
                "approved_by": "user",
                "gate": "new_failure_chain",
                "failure_fingerprint": fingerprint,
                "issue_id": "ISSUE-706",
                "failure_class": "implementation_failure",
                "originating_baseline": state_payload["git_baseline"],
                "reason": "same approval",
            }
            approval_v2 = dict(approval_v1, version=2)
            attempt = failure_control.record_attempt(
                [],
                dict(
                    facts,
                    new_chain=True,
                    new_chain_approval_id="DEC-706",
                    new_chain_approval_version=1,
                    new_chain_approval_hash=failure_control.approval_record_hash(
                        approval_v1
                    ),
                    new_chain_reason="same approval",
                ),
            )["record"]
            attempt["new_chain_approval"].pop("approval_version")
            attempt["new_chain_approval"].pop("approval_hash")
            state_payload["ledger"] = [approval_v1, approval_v2]
            state_payload["failure_attempts"] = [attempt]
            state_path.write_text(json.dumps(state_payload), encoding="utf-8")
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("reconcile", json.loads(result.stdout)["error"]["message"])
            self.assertEqual(self._yaml_snapshot(workflow), before)

    def _legacy_recovery_task(self, workflow, *, ambiguous=False):
        state_path = workflow / "系统" / "state.yaml"
        state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        facts = {
            "failure_class": "implementation_failure",
            "issue_id": "ISSUE-704",
            "failed_command": ["python3 -m unittest"],
            "failed_acceptance": [],
            "originating_baseline": state_payload["git_baseline"],
            "current_baseline": state_payload["git_baseline"],
        }
        history = []
        for _ in range(3):
            history = failure_control.record_attempt(history, facts)["history"]
        fingerprint = history[-1]["fingerprint"]
        approval_v1 = {
            "id": "DEC-704",
            "type": "DEC",
            "version": 1,
            "status": "approved",
            "approved_by": "user",
            "gate": "failure_recovery",
            "repair_mode": "recovery",
            "failure_fingerprint": fingerprint,
            "issue_id": "ISSUE-704",
            "reason": "approve legacy recovery",
        }
        approval_v2 = dict(
            approval_v1,
            version=2,
            gate="failure_recovery" if ambiguous else "route_selection",
        )
        task = {
            "id": "TASK-704",
            "task_type": "repair",
            "repair_mode": "recovery",
            "failure_class": "implementation_failure",
            "failure_fingerprint": fingerprint,
            "attempt_count": 3,
            "repair_approval_id": "DEC-704",
        }
        state_payload["ledger"] = [approval_v1, approval_v2]
        state_payload["failure_attempts"] = history
        state_payload["tasks"] = [task]
        state_path.write_text(json.dumps(state_payload), encoding="utf-8")
        tasks_path = workflow / "系统" / "tasks.yaml"
        tasks_payload = json.loads(tasks_path.read_text(encoding="utf-8"))
        tasks_payload["tasks"] = [task]
        tasks_path.write_text(json.dumps(tasks_payload), encoding="utf-8")
        return state_path, tasks_path, approval_v1

    def test_migration_snapshots_the_unique_historical_repair_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path, tasks_path, approval_v1 = self._legacy_recovery_task(workflow)

            migrated = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(migrated.returncode, 0, migrated.stdout)
            migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
            state_task = migrated_state["tasks"][0]
            manifest_task = json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"][0]
            self.assertEqual(state_task, manifest_task)
            self.assertEqual(state_task.get("repair_approval_version"), 1)
            self.assertEqual(
                state_task.get("repair_approval_hash"),
                failure_control.approval_record_hash(approval_v1),
            )
            workflow_ops._validate_repair_task_policy(state_task, migrated_state)

    def test_migration_rejects_an_ambiguous_repair_approval_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            self._legacy_recovery_task(workflow, ambiguous=True)
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("reconcile", json.loads(result.stdout)["error"]["message"])
            self.assertEqual(
                self._yaml_snapshot(workflow), before
            )

    def test_migration_rejects_a_conflicting_partial_repair_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path, tasks_path, _ = self._legacy_recovery_task(workflow)
            for path in (state_path, tasks_path):
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["tasks"][0]["repair_approval_version"] = 2
                path.write_text(json.dumps(payload), encoding="utf-8")
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("reconcile", json.loads(result.stdout)["error"]["message"])
            self.assertEqual(self._yaml_snapshot(workflow), before)

    def test_migration_rejects_a_missing_repair_approval_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            env, workflow = self._legacy_workflow(Path(directory))
            state_path, _, _ = self._legacy_recovery_task(workflow)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            payload["ledger"] = []
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            before = self._yaml_snapshot(workflow)

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("reconcile", json.loads(result.stdout)["error"]["message"])
            self.assertEqual(self._yaml_snapshot(workflow), before)


if __name__ == "__main__":
    unittest.main()
