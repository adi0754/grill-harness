import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "skills" / "grill-harness" / "scripts" / "grh.py"


def run_cli(*arguments, env=None):
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class GrillHarnessCliTests(unittest.TestCase):
    def test_argparse_errors_are_stable_json_on_stdout(self):
        cases = (
            ((), None),
            (("unknown",), None),
            (("identify",), "identify"),
            (("identify", "--unknown"), "identify"),
        )
        for arguments, command in cases:
            with self.subTest(arguments=arguments):
                result = run_cli(*arguments)

                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, "")
                payload = json.loads(result.stdout)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["command"], command)
                self.assertEqual(payload["error"]["type"], "usage")

    def test_identify_emits_project_identity_as_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()

            result = run_cli("identify", "--project", str(project))

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["command"], "identify")
            self.assertEqual(payload["project"]["normalized_path"], str(project.resolve()))
            self.assertFalse(payload["project"]["is_git"])

    def test_preflight_accepts_explicit_skill_roots_and_emits_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "skills"
            root.mkdir()
            for name in ("grilling", "domain-modeling", "codebase-design"):
                directory = root / name
                directory.mkdir()
                (directory / "SKILL.md").write_text(
                    "---\nname: {}\ndescription: Use when testing.\n---\n".format(name),
                    encoding="utf-8",
                )
            env = dict(os.environ)
            env["PATH"] = ""

            result = run_cli("preflight", "--skill-root", str(root), env=env)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["preflight"]["ready"])
            self.assertFalse(payload["preflight"]["actions_performed"])

    def test_status_reports_not_started_without_creating_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            project = Path(temp_dir) / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)

            result = run_cli("status", "--project", str(project), env=env)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "not_started")
            self.assertIsNone(payload["workflow_path"])
            self.assertTrue(payload["reconciliation"]["valid"])
            self.assertEqual(payload["next_eligible_phase"], "preflight")
            self.assertFalse(root.exists())

    def test_init_creates_minimal_workflow_only_under_test_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            (project / "README.md").write_text("fixture\n", encoding="utf-8")
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)

            result = run_cli(
                "init",
                "--project",
                str(project),
                "--workflow-name",
                "发布检查",
                "--workflow-key",
                "release-check",
                "--created-date",
                "2026-07-12",
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["created"])
            workflow = Path(payload["workflow_path"])
            self.assertTrue(workflow.name.endswith(payload["workflow_id"][:8]))
            self.assertTrue(str(workflow).startswith(str(root.resolve())))
            self.assertFalse((project / ".grill-harness").exists())
            self.assertEqual((project / "README.md").read_text(encoding="utf-8"), "fixture\n")
            self.assertTrue((root / "项目索引.yaml").is_file())
            self.assertTrue((workflow.parent.parent / "项目信息.yaml").is_file())
            for directory in ("核心文档", "过程产物", "最终产物", "系统"):
                self.assertTrue((workflow / directory).is_dir())
            for filename in ("state.yaml", "artifacts.yaml", "tasks.yaml", "evidence.yaml"):
                self.assertTrue((workflow / "系统" / filename).is_file())
            self.assertEqual(list(workflow.parent.glob(".*.tmp")), [])

            state_payload = json.loads((workflow / "系统" / "state.yaml").read_text(encoding="utf-8"))
            self.assertEqual(state_payload["workflow_id"], payload["workflow_id"])
            self.assertEqual(state_payload["project_id"], payload["project_id"])
            self.assertEqual(state_payload["phases"][0], {"id": "preflight", "status": "pending"})

            status = run_cli("status", "--project", str(project), env=env)
            self.assertEqual(status.returncode, 0, status.stdout)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["status"], "active")
            self.assertEqual(status_payload["workflow_path"], str(workflow / "系统" / "state.yaml"))

    def test_init_is_idempotent_and_does_not_overwrite_existing_workflow_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            arguments = (
                "init", "--project", str(project), "--workflow-name", "发布检查",
                "--workflow-key", "release-check", "--created-date", "2026-07-12",
            )
            first = run_cli(*arguments, env=env)
            self.assertEqual(first.returncode, 0, first.stdout)
            workflow = Path(json.loads(first.stdout)["workflow_path"])
            sentinel = workflow / "核心文档" / "用户内容.md"
            sentinel.write_text("keep\n", encoding="utf-8")

            second = run_cli(*arguments, env=env)

            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertFalse(json.loads(second.stdout)["created"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")

    def test_init_refuses_to_complete_a_partial_existing_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            first = run_cli(
                "init", "--project", str(project), "--workflow-name", "发布检查",
                "--workflow-key", "release-check", "--created-date", "2026-07-12",
                env=env,
            )
            workflow = Path(json.loads(first.stdout)["workflow_path"])
            state_file = workflow / "系统" / "state.yaml"
            state_file.unlink()
            sentinel = workflow / "核心文档" / "用户内容.md"
            sentinel.write_text("keep\n", encoding="utf-8")

            second = run_cli(
                "init", "--project", str(project), "--workflow-name", "发布检查",
                "--workflow-key", "release-check", "--created-date", "2026-07-12",
                env=env,
            )

            self.assertEqual(second.returncode, 2)
            self.assertFalse(state_file.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")

    def test_init_rejects_invalid_created_date_as_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()

            result = run_cli(
                "init", "--project", str(project), "--workflow-name", "发布检查",
                "--created-date", "12-07-2026",
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["command"], "init")

    def test_status_reconciles_an_explicit_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            workflow_path = Path(temp_dir) / "state.yaml"
            workflow_path.write_text(
                json.dumps(
                    {
                        "phases": [
                            {"id": "alignment", "status": "in_progress"},
                        ],
                        "artifacts": [],
                        "tasks": [],
                        "evidence": [],
                        "gates": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_cli(
                "status",
                "--project",
                str(project),
                "--workflow",
                str(workflow_path),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "active")
            self.assertEqual(payload["current_phase"], "alignment")
            self.assertEqual(payload["next_eligible_phase"], "alignment")
            self.assertTrue(payload["reconciliation"]["valid"])

    def test_status_blocks_guarded_current_phase_without_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            workflow_path = Path(temp_dir) / "state.yaml"
            workflow_path.write_text(
                json.dumps(
                    {
                        "phases": [
                            {"id": "preflight", "status": "pending"},
                            {"id": "implementation", "status": "in_progress"},
                        ],
                        "artifacts": [],
                        "tasks": [],
                        "evidence": [],
                        "gates": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_cli(
                "status",
                "--project",
                str(project),
                "--workflow",
                str(workflow_path),
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "recovery_required")
            self.assertEqual(payload["current_phase"], "implementation")
            self.assertIsNone(payload["next_eligible_phase"])
            self.assertEqual(
                payload["reconciliation"]["conflicts"][-1]["code"],
                "PHASE_GATE",
            )

    def test_status_reports_malformed_gates_as_reconciliation_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            workflow_path = Path(temp_dir) / "state.yaml"
            workflow_path.write_text(
                json.dumps(
                    {
                        "phases": [{"id": "implementation", "status": "in_progress"}],
                        "gates": [],
                    }
                ),
                encoding="utf-8",
            )

            result = run_cli(
                "status",
                "--project",
                str(project),
                "--workflow",
                str(workflow_path),
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "recovery_required")
            self.assertEqual(
                payload["reconciliation"]["conflicts"][-1]["code"],
                "PHASE_GATE",
            )

    def test_reconcile_reports_conflicts_as_machine_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_path = Path(temp_dir) / "state.yaml"
            workflow_path.write_text(
                json.dumps(
                    {
                        "phases": [
                            {"id": "alignment", "status": "pending"},
                            {"id": "alignment", "status": "pending"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = run_cli("reconcile", "--workflow", str(workflow_path))

            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["reconciliation"]["valid"])
            self.assertEqual(
                payload["reconciliation"]["conflicts"][0]["code"],
                "DUPLICATE_ID",
            )

    def test_reconcile_blocks_completed_guarded_phase_without_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_path = Path(temp_dir) / "state.yaml"
            workflow_path.write_text(
                json.dumps(
                    {
                        "phases": [
                            {
                                "id": "independent_assurance",
                                "status": "completed",
                                "artifacts": ["ART-001"],
                                "evidence": ["EVD-001"],
                            }
                        ],
                        "artifacts": [{"id": "ART-001", "status": "completed"}],
                        "tasks": [],
                        "evidence": [{"id": "EVD-001", "status": "completed"}],
                        "gates": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_cli("reconcile", "--workflow", str(workflow_path))

            self.assertEqual(result.returncode, 1, result.stdout)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(
                payload["reconciliation"]["conflicts"][-1]["code"],
                "PHASE_GATE",
            )

    def test_upstream_check_is_read_only_machine_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            facts = Path(temp_dir) / "facts.json"
            manifest = {
                "repository": "example/repo",
                "ref": "main",
                "commit": "abc",
                "checked_at": "2026-07-11T00:00:00Z",
                "upstream_updated_at": "2026-07-10T00:00:00Z",
                "license": "MIT",
                "source_paths": {"grilling": "skills/grilling/SKILL.md"},
                "hashes": {"skills/grilling/SKILL.md": "hash-v1"},
                "behavior_contracts": {"grilling": {"summary": "ask decisions"}},
                "local_differences": [],
                "risks": [],
                "last_test_results": {"status": "passed"},
            }
            previous.write_text(json.dumps(manifest), encoding="utf-8")
            facts.write_text(
                json.dumps(
                    {
                        "repository": manifest["repository"],
                        "ref": manifest["ref"],
                        "commit": manifest["commit"],
                        "upstream_updated_at": manifest["upstream_updated_at"],
                        "license": manifest["license"],
                        "sources": {
                            "grilling": {
                                "path": "skills/grilling/SKILL.md",
                                "hash": "hash-v1",
                            }
                        },
                        "behavior_contracts": {
                            "grilling": {"summary": "ask decisions"}
                        },
                        "local_differences": [],
                        "risks": [],
                        "last_test_results": {"status": "passed"},
                    }
                ),
                encoding="utf-8",
            )

            result = run_cli(
                "upstream-check",
                "--previous",
                str(previous),
                "--facts",
                str(facts),
                "--checked-at",
                "2026-07-12T00:00:00Z",
                "--offline",
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["upstream"]["actions_performed"])
            self.assertFalse(payload["upstream"]["accepted_upstream_changes"])


if __name__ == "__main__":
    unittest.main()
