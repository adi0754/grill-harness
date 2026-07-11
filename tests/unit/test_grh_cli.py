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
