import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "grill-harness" / "scripts" / "grh.py"


def run_cli(*arguments, env=None):
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class MigrationTests(unittest.TestCase):
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
            before = {
                path: path.read_bytes()
                for path in (workflow / "系统").glob("*.yaml")
            }

            result = run_cli("migrate", "--workflow", str(workflow), env=env)

            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                {path: path.read_bytes() for path in before},
                before,
            )


if __name__ == "__main__":
    unittest.main()
