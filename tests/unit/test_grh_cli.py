import json
import os
import shutil
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


def run_cli_at(cli, *arguments, env=None):
    return subprocess.run(
        [sys.executable, str(cli), *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class GrillHarnessCliTests(unittest.TestCase):
    def _isolated_harness(self, root, entries, required_capabilities=False):
        skills_root = Path(root) / "skills"
        source_root = REPO_ROOT / "skills"
        for entry in entries:
            shutil.copytree(source_root / entry, skills_root / entry)
        if required_capabilities:
            for capability in ("grilling", "domain-modeling", "codebase-design"):
                path = skills_root / capability
                path.mkdir(parents=True)
                path.joinpath("SKILL.md").write_text(
                    "---\nname: {}\ndescription: Use when testing.\n---\n".format(capability),
                    encoding="utf-8",
                )
        return skills_root, skills_root / "grill-harness" / "scripts" / "grh.py"

    def test_entry_check_blocks_when_public_installation_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            _, cli = self._isolated_harness(base, ("grill-harness", "grh-start"))
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({"GRILL_HARNESS_TEST_ROOT": str(base / "storage"), "PATH": ""})

            result = run_cli_at(
                cli, "entry-check", "--entry", "grh-start", "--project", str(project),
                env=env,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["preflight"]["entry_ready"])
            self.assertEqual(payload["decision"]["reason_code"], "harness_installation_incomplete")
            self.assertIn("grh-plan", payload["decision"]["missing_prerequisites"])
            self.assertFalse((base / "storage").exists())

    def test_entry_check_blocks_when_thin_entry_contract_is_incompatible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            entries = (
                "grill-harness", "grh-start", "grh-plan", "grh-run", "grh-check",
                "grh-recover", "grh-learn", "grh-upstream-check",
            )
            skills_root, cli = self._isolated_harness(base, entries)
            run_skill = skills_root / "grh-run" / "SKILL.md"
            run_skill.write_text(
                run_skill.read_text(encoding="utf-8").replace(
                    "entry_core_contract_version: 1", "entry_core_contract_version: 999"
                ),
                encoding="utf-8",
            )
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({"GRILL_HARNESS_TEST_ROOT": str(base / "storage"), "PATH": ""})

            result = run_cli_at(
                cli, "entry-check", "--entry", "grh-run", "--project", str(project),
                env=env,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["preflight"]["harness_installation"]["incompatible_entries"],
                ["grh-run"],
            )
            self.assertEqual(payload["decision"]["reason_code"], "harness_contract_incompatible")
            self.assertFalse((base / "storage").exists())

    def test_entry_check_blocks_mutating_entry_when_required_capabilities_are_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            entries = (
                "grill-harness", "grh-start", "grh-plan", "grh-run", "grh-check",
                "grh-recover", "grh-learn", "grh-upstream-check",
            )
            _, cli = self._isolated_harness(base, entries)
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({"GRILL_HARNESS_TEST_ROOT": str(base / "storage"), "PATH": ""})

            result = run_cli_at(
                cli, "entry-check", "--entry", "grh-start", "--project", str(project),
                env=env,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["decision"]["reason_code"], "missing_required_capabilities"
            )
            self.assertEqual(
                payload["decision"]["missing_prerequisites"],
                ["grilling", "domain-modeling", "codebase-design"],
            )
            self.assertFalse(payload["decision"]["eligible"])
            self.assertFalse((base / "storage").exists())

    def test_entry_check_allows_read_only_diagnostics_without_required_capabilities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            entries = (
                "grill-harness", "grh-start", "grh-plan", "grh-run", "grh-check",
                "grh-recover", "grh-learn", "grh-upstream-check",
            )
            _, cli = self._isolated_harness(base, entries)
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({"GRILL_HARNESS_TEST_ROOT": str(base / "storage"), "PATH": ""})

            for entry in ("grill-harness", "grh-upstream-check"):
                with self.subTest(entry=entry):
                    result = run_cli_at(
                        cli, "entry-check", "--entry", entry, "--project", str(project),
                        env=env,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertTrue(payload["decision"]["eligible"])
                    self.assertEqual(payload["preflight"]["missing_required"], [
                        "grilling", "domain-modeling", "codebase-design"
                    ])
            self.assertFalse((base / "storage").exists())

    def test_entry_check_keeps_learn_search_available_without_required_capabilities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            entries = (
                "grill-harness", "grh-start", "grh-plan", "grh-run", "grh-check",
                "grh-recover", "grh-learn", "grh-upstream-check",
            )
            _, cli = self._isolated_harness(base, entries)
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({
                "GRILL_HARNESS_TEST_ROOT": str(base / "storage"),
                "PATH": "/usr/bin:/bin",
            })
            initialized = run_cli_at(
                cli, "init", "--project", str(project), "--workflow-name", "学习",
                "--created-date", "2026-07-12", env=env,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
            workflow = json.loads(initialized.stdout)["workflow_path"]

            result = run_cli_at(
                cli, "entry-check", "--entry", "grh-learn", "--project", str(project),
                "--workflow", workflow, "--requested-scope", "search_knowledge", env=env,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["decision"]["eligible"])
            self.assertEqual(payload["decision"]["allowed_scope"], ["search_knowledge"])
            self.assertEqual(payload["decision"]["reason_code"], "eligible_with_restricted_scope")
            self.assertEqual(payload["preflight"]["missing_required"], [
                "grilling", "domain-modeling", "codebase-design"
            ])
            self.assertTrue((base / "storage").exists())

    def test_entry_check_blocks_learn_retrospective_without_required_capabilities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            entries = (
                "grill-harness", "grh-start", "grh-plan", "grh-run", "grh-check",
                "grh-recover", "grh-learn", "grh-upstream-check",
            )
            _, cli = self._isolated_harness(base, entries)
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({
                "GRILL_HARNESS_TEST_ROOT": str(base / "storage"),
                "PATH": "/usr/bin:/bin",
            })
            initialized = run_cli_at(
                cli, "init", "--project", str(project), "--workflow-name", "复盘",
                "--created-date", "2026-07-12", env=env,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
            workflow = json.loads(initialized.stdout)["workflow_path"]

            result = run_cli_at(
                cli, "entry-check", "--entry", "grh-learn", "--project", str(project),
                "--workflow", workflow, "--requested-scope", "retrospective", env=env,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["decision"]["eligible"])
            self.assertEqual(payload["decision"]["allowed_scope"], [])
            self.assertEqual(
                payload["decision"]["reason_code"], "missing_required_capabilities"
            )
            self.assertIn("retrospective", payload["decision"]["forbidden_scope"])
            self.assertTrue((base / "storage").exists())

    def test_entry_check_allows_start_for_not_started_project_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            entries = (
                "grill-harness", "grh-start", "grh-plan", "grh-run", "grh-check",
                "grh-recover", "grh-learn", "grh-upstream-check",
            )
            _, cli = self._isolated_harness(
                base, entries, required_capabilities=True
            )
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({"GRILL_HARNESS_TEST_ROOT": str(root), "PATH": ""})

            result = run_cli_at(
                cli,
                "entry-check", "--entry", "grh-start", "--project", str(project), env=env
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["decision"]["eligible"])
            self.assertEqual(payload["status"]["status"], "not_started")
            self.assertFalse(payload["decision"]["will_auto_route"])
            self.assertFalse(root.exists())

    def test_entry_check_blocks_run_when_workflow_has_not_started(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env.update({"GRILL_HARNESS_TEST_ROOT": str(root), "PATH": ""})

            result = run_cli(
                "entry-check", "--entry", "grh-run", "--project", str(project), env=env
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["decision"]["reason_code"], "workflow_not_started")
            self.assertEqual(payload["decision"]["recommended_entry"], "grh-start")
            self.assertFalse(root.exists())

    def test_entry_check_blocks_run_without_final_spec_approval_and_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            initialized = run_cli(
                "init", "--project", str(project), "--workflow-name", "检查",
                "--created-date", "2026-07-12", env=env,
            )
            workflow = Path(json.loads(initialized.stdout)["workflow_path"])
            before = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}
            env["PATH"] = "/usr/bin:/bin"

            result = run_cli(
                "entry-check", "--entry", "grh-run", "--project", str(project),
                "--workflow", str(workflow), env=env,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("final_spec_approval", payload["decision"]["missing_prerequisites"])
            after = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_entry_check_review_only_scope_excludes_final_acceptance_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            entries = (
                "grill-harness", "grh-start", "grh-plan", "grh-run", "grh-check",
                "grh-recover", "grh-learn", "grh-upstream-check",
            )
            _, cli = self._isolated_harness(
                base, entries, required_capabilities=True
            )
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            initialized = run_cli_at(
                cli,
                "init", "--project", str(project), "--workflow-name", "检查",
                "--created-date", "2026-07-12", env=env,
            )
            workflow = Path(json.loads(initialized.stdout)["workflow_path"])
            before = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}
            env["PATH"] = "/usr/bin:/bin"

            result = run_cli_at(
                cli,
                "entry-check", "--entry", "grh-check", "--project", str(project),
                "--workflow", str(workflow), "--requested-scope", "review", env=env,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["decision"]["allowed_scope"], ["review"])
            self.assertNotIn("final_acceptance", payload["decision"]["allowed_scope"])
            self.assertFalse(payload["decision"]["will_auto_route"])
            after = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

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
            self.assertEqual(state_payload["workflow_version"], 1)
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

    def test_init_rejects_complete_workflow_with_conflicting_identity_without_writes(self):
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
            workflow = Path(json.loads(first.stdout)["workflow_path"])
            state_file = workflow / "系统" / "state.yaml"
            state_payload = json.loads(state_file.read_text(encoding="utf-8"))
            state_payload["workflow_name"] = "冲突名称"
            state_file.write_text(json.dumps(state_payload), encoding="utf-8")
            sentinel = workflow / "核心文档" / "用户内容.md"
            sentinel.write_text("keep\n", encoding="utf-8")
            before = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}

            second = run_cli(*arguments, env=env)

            self.assertEqual(second.returncode, 2)
            payload = json.loads(second.stdout)
            self.assertEqual(payload["command"], "init")
            self.assertIn("identity", payload["error"]["message"])
            after = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_init_rejects_malformed_manifest_without_writes(self):
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
            workflow = Path(json.loads(first.stdout)["workflow_path"])
            manifest = workflow / "系统" / "artifacts.yaml"
            manifest.write_text('{"artifacts":"not-a-list"}\n', encoding="utf-8")
            sentinel = workflow / "最终产物" / "用户内容.md"
            sentinel.write_text("keep\n", encoding="utf-8")
            before = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}

            second = run_cli(*arguments, env=env)

            self.assertEqual(second.returncode, 2)
            payload = json.loads(second.stdout)
            self.assertEqual(payload["command"], "init")
            self.assertIn("artifacts", payload["error"]["message"])
            after = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_init_rejects_manifest_that_contradicts_state_without_writes(self):
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
            workflow = Path(json.loads(first.stdout)["workflow_path"])
            manifest = workflow / "系统" / "artifacts.yaml"
            manifest.write_text(
                '{"schema_version":1,"workflow_version":1,'
                '"artifacts":[{"id":"ART-contradiction"}]}\n',
                encoding="utf-8",
            )
            before = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}

            second = run_cli(*arguments, env=env)

            self.assertEqual(second.returncode, 2)
            payload = json.loads(second.stdout)
            self.assertIn("contradicts", payload["error"]["message"])
            after = {path: path.read_bytes() for path in workflow.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_concurrent_init_preserves_every_project_index_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            processes = []
            for number in range(12):
                project = base / "project-{}".format(number)
                project.mkdir()
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable, str(CLI), "init",
                            "--project", str(project),
                            "--workflow-name", "并发检查",
                            "--workflow-key", "concurrent-{}".format(number),
                            "--created-date", "2026-07-12",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=env,
                    )
                )

            results = [process.communicate(timeout=20) + (process.returncode,) for process in processes]

            self.assertTrue(all(returncode == 0 for _, _, returncode in results), results)
            index = json.loads((root / "项目索引.yaml").read_text(encoding="utf-8"))
            self.assertEqual(len(index["projects"]), 12)
            self.assertEqual(len({item["project_id"] for item in index["projects"]}), 12)

    def test_concurrent_init_of_same_workflow_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            command = [
                sys.executable, str(CLI), "init",
                "--project", str(project),
                "--workflow-name", "同一工作流",
                "--workflow-key", "same",
                "--created-date", "2026-07-12",
            ]
            processes = [
                subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
                for _ in range(8)
            ]

            results = [process.communicate(timeout=20) + (process.returncode,) for process in processes]

            self.assertTrue(all(code == 0 for _, _, code in results), results)
            payloads = [json.loads(stdout) for stdout, _, _ in results]
            self.assertEqual(sum(item["created"] for item in payloads), 1)
            self.assertEqual(len({item["workflow_path"] for item in payloads}), 1)

    def test_status_detects_state_and_manifest_divergence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            project = base / "project"
            project.mkdir()
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            created = run_cli(
                "init", "--project", str(project), "--workflow-name", "分叉检查",
                "--workflow-key", "divergence", "--created-date", "2026-07-12",
                env=env,
            )
            workflow = Path(json.loads(created.stdout)["workflow_path"])
            (workflow / "系统" / "tasks.yaml").write_text(
                '{"schema_version":1,"workflow_version":1,"tasks":[{"id":"TASK-X"}]}\n',
                encoding="utf-8",
            )

            result = run_cli("status", "--project", str(project), env=env)

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "recovery_required")
            self.assertIn("MANIFEST_DIVERGENCE", {
                item["code"] for item in payload["reconciliation"]["conflicts"]
            })

    def test_moved_git_repository_reuses_unique_stored_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "storage"
            original = base / "original" / "project"
            original.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(original)], check=True)
            subprocess.run(["git", "-C", str(original), "config", "user.name", "Tests"], check=True)
            subprocess.run(["git", "-C", str(original), "config", "user.email", "tests@example.com"], check=True)
            subprocess.run(["git", "-C", str(original), "remote", "add", "origin", "https://github.com/example/project.git"], check=True)
            (original / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(original), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(original), "commit", "-qm", "init"], check=True)
            env = dict(os.environ)
            env["GRILL_HARNESS_TEST_ROOT"] = str(root)
            created = run_cli(
                "init", "--project", str(original), "--workflow-name", "移动检查",
                "--workflow-key", "move", "--created-date", "2026-07-12", env=env,
            )
            expected = json.loads(created.stdout)["workflow_path"]
            moved = base / "moved" / "project"
            moved.parent.mkdir()
            original.rename(moved)

            result = run_cli("status", "--project", str(moved), env=env)

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)["workflow_path"], str(Path(expected) / "系统" / "state.yaml"))

            second = run_cli(
                "init", "--project", str(moved), "--workflow-name", "第二工作流",
                "--workflow-key", "move-second", "--created-date", "2026-07-12",
                env=env,
            )

            self.assertEqual(second.returncode, 0, second.stdout)
            second_path = Path(json.loads(second.stdout)["workflow_path"])
            self.assertEqual(second_path.parent, Path(expected).parent)
            index = json.loads((root / "项目索引.yaml").read_text(encoding="utf-8"))
            self.assertEqual(len(index["projects"]), 1)
            self.assertEqual(
                index["projects"][0]["normalized_path"], str(moved.resolve())
            )

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

    def test_status_returns_machine_json_for_wrong_collection_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            workflow_path = Path(temp_dir) / "state.yaml"
            workflow_path.write_text(
                json.dumps(
                    {
                        "phases": None,
                        "artifacts": [],
                        "tasks": [],
                        "evidence": [],
                        "gates": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_cli(
                "status", "--project", str(project), "--workflow", str(workflow_path)
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "recovery_required")
            self.assertIn("INVALID_COLLECTION", {
                item["code"] for item in payload["reconciliation"]["conflicts"]
            })

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
            manifest = json.loads(
                (REPO_ROOT / "skills" / "grill-harness" / "references" / "上游清单.yaml")
                .read_text(encoding="utf-8")
            )
            previous.write_text(json.dumps(manifest), encoding="utf-8")
            facts.write_text(
                json.dumps(
                    {
                        "repository": manifest["repository"],
                        "ref": manifest["ref"],
                        "commit": manifest["commit"],
                        "upstream_updated_at": manifest["upstream_updated_at"],
                        "upstream_release": manifest["upstream_release"],
                        "license": manifest["license"],
                        "license_path": manifest["license_path"],
                        "copyright": manifest["copyright"],
                        "hash_algorithm": manifest["hash_algorithm"],
                        "tracked_capabilities": manifest["tracked_capabilities"],
                        "sources": {
                            capability: {
                                "path": path,
                                "hash": manifest["hashes"][path],
                            }
                            for capability, path in manifest["source_paths"].items()
                        },
                        "reference_files": manifest["reference_files"],
                        "behavior_contracts": manifest["behavior_contracts"],
                        "design_inputs": manifest["design_inputs"],
                        "local_differences": manifest["local_differences"],
                        "local_extension_points": manifest["local_extension_points"],
                        "risks": manifest["risks"],
                        "last_test_results": manifest["last_test_results"],
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
