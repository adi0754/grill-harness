import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "upstream"
sys.path.insert(0, str(SCRIPTS_DIR))

import preflight


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, command):
        self.calls.append(list(command))
        response = self.responses.get(tuple(command))
        if isinstance(response, Exception):
            raise response
        return response


class PreflightTests(unittest.TestCase):
    PUBLIC_ENTRIES = (
        "grill-harness",
        "grh-start",
        "grh-plan",
        "grh-run",
        "grh-check",
        "grh-recover",
        "grh-learn",
        "grh-upstream-check",
    )

    def _skill(self, root, name, metadata_name=None):
        path = Path(root) / name
        path.mkdir(parents=True)
        path.joinpath("SKILL.md").write_text(
            "---\nname: {}\n---\n".format(metadata_name or name), encoding="utf-8"
        )
        return path

    def _safe_cli_responses(self, project_payload, global_payload):
        return {
            ("npx", "skills", "list", "--json"): {"returncode": 0, "stdout": json.dumps(project_payload)},
            ("npx", "skills", "list", "-g", "--json"): {"returncode": 0, "stdout": json.dumps(global_payload)},
            ("npx", "skills", "--help"): {
                "returncode": 0,
                "stdout": (FIXTURES / "skills-help.txt").read_text(encoding="utf-8"),
            },
        }

    def _public_installation(
        self,
        root,
        contract_version=1,
        metadata_names=None,
        entry_versions=None,
        create_core_script=True,
    ):
        metadata_names = metadata_names or {}
        entry_versions = entry_versions or {}
        entries = []
        for name in self.PUBLIC_ENTRIES:
            path = self._skill(root, name, metadata_name=metadata_names.get(name))
            path.joinpath("SKILL.md").write_text(
                "---\nname: {}\nentry_core_contract_version: {}\n---\n".format(
                    metadata_names.get(name, name), entry_versions.get(name, 1)
                ),
                encoding="utf-8",
            )
            entries.append({"name": name, "path": str(path)})
        contract = Path(root) / "grill-harness" / "references" / "入口内核契约.json"
        contract.parent.mkdir(parents=True)
        contract.write_text(
            json.dumps({
                "contract_version": contract_version,
                "core": {"entry_check_script": "scripts/grh.py"},
                "entries": {name: {} for name in self.PUBLIC_ENTRIES},
            }),
            encoding="utf-8",
        )
        if create_core_script:
            script = Path(root) / "grill-harness" / "scripts" / "grh.py"
            script.parent.mkdir(parents=True)
            script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        return entries

    def test_default_runner_times_out_without_raising(self):
        timeout = subprocess.TimeoutExpired(
            ["npx", "skills", "list", "--json"], 20
        )
        with mock.patch.object(subprocess, "run", side_effect=timeout) as run:
            response = preflight._default_runner(
                ["npx", "skills", "list", "--json"]
            )

        self.assertEqual(response["returncode"], 124)
        self.assertIn("timed out", response["stderr"])
        self.assertEqual(run.call_args.kwargs["timeout"], 20)

    def test_default_runner_resolves_the_command_through_path(self):
        # Windows npx is an npx.cmd shim that bare-name CreateProcess lookup
        # misses; the runner must resolve it via PATH before executing.
        with mock.patch.object(
            preflight.shutil, "which", return_value="/resolved/npx.cmd"
        ) as which:
            with mock.patch.object(
                subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout="[]", stderr=""),
            ) as run:
                response = preflight._default_runner(["npx", "skills", "list", "--json"])

        which.assert_called_once_with("npx")
        self.assertEqual(
            run.call_args.args[0],
            ["/resolved/npx.cmd", "skills", "list", "--json"],
        )
        self.assertEqual(response["returncode"], 0)

    def test_default_runner_keeps_the_bare_command_when_path_lookup_fails(self):
        with mock.patch.object(preflight.shutil, "which", return_value=None):
            with mock.patch.object(
                subprocess, "run", side_effect=FileNotFoundError("npx")
            ) as run:
                with self.assertRaises(FileNotFoundError):
                    preflight._default_runner(["npx", "skills", "list", "--json"])

        self.assertEqual(
            run.call_args.args[0], ["npx", "skills", "list", "--json"]
        )

    def test_complete_public_installation_is_entry_ready_without_changing_dependency_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public_entries = self._public_installation(root)
            dependencies = [
                {"name": name, "path": str(self._skill(root, name))}
                for name in preflight.REQUIRED_CAPABILITIES
            ]
            runner = FakeRunner(self._safe_cli_responses(
                {"skills": public_entries + dependencies}, {"skills": []}
            ))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-plan",
            )

            self.assertTrue(report["ready"])
            self.assertTrue(report["entry_ready"])
            self.assertTrue(report["overall_ready"])
            self.assertEqual(report["harness_installation"]["missing_entries"], [])
            self.assertEqual(
                report["harness_installation"]["core_path"],
                str(root / "grill-harness"),
            )
            self.assertTrue(report["harness_installation"]["contract_compatible"])
            self.assertFalse(report["actions_performed"])

    def test_incomplete_public_installation_reports_every_missing_entry_and_keeps_ready_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            learn = self._skill(root, "grh-learn")
            dependencies = [
                {"name": name, "path": str(self._skill(root, name))}
                for name in preflight.REQUIRED_CAPABILITIES
            ]
            runner = FakeRunner(self._safe_cli_responses(
                {"skills": [{"name": "grh-learn", "path": str(learn)}] + dependencies},
                {"skills": []},
            ))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-learn",
            )

            self.assertTrue(report["ready"])
            self.assertFalse(report["entry_ready"])
            self.assertFalse(report["overall_ready"])
            self.assertIn("grill-harness", report["harness_installation"]["missing_entries"])
            self.assertIsNone(report["harness_installation"]["core_path"])
            self.assertFalse(report["harness_installation"]["contract_compatible"])
            self.assertFalse(report["actions_performed"])

    def test_wrong_public_entry_frontmatter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self._public_installation(
                root, metadata_names={"grh-check": "wrong-name"}
            )
            runner = FakeRunner(self._safe_cli_responses({"skills": entries}, {"skills": []}))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-check",
            )

            self.assertFalse(report["entry_ready"])
            self.assertIn("grh-check", report["harness_installation"]["missing_entries"])
            check = next(
                item for item in report["harness_installation"]["entries"]
                if item["name"] == "grh-check"
            )
            self.assertEqual(check["status"], "stale-metadata")

    def test_incompatible_core_contract_blocks_entry_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self._public_installation(root, contract_version=999)
            runner = FakeRunner(self._safe_cli_responses({"skills": entries}, {"skills": []}))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-run",
            )

            self.assertFalse(report["entry_ready"])
            self.assertFalse(report["harness_installation"]["contract_compatible"])
            self.assertEqual(report["harness_installation"]["contract_version"], 999)

    def test_incompatible_thin_entry_contract_blocks_entry_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self._public_installation(
                root, entry_versions={"grh-run": 999}
            )
            runner = FakeRunner(self._safe_cli_responses({"skills": entries}, {"skills": []}))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-run",
            )

            self.assertFalse(report["entry_ready"])
            self.assertFalse(report["harness_installation"]["contract_compatible"])
            self.assertEqual(
                report["harness_installation"]["incompatible_entries"], ["grh-run"]
            )

    def test_missing_contract_declared_core_script_blocks_entry_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self._public_installation(root, create_core_script=False)
            runner = FakeRunner(self._safe_cli_responses({"skills": entries}, {"skills": []}))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-plan",
            )

            installation = report["harness_installation"]
            self.assertFalse(report["entry_ready"])
            self.assertFalse(installation["contract_compatible"])
            self.assertEqual(installation["core_script"], "scripts/grh.py")
            self.assertFalse(installation["core_script_verified"])

    def test_contract_cannot_substitute_skill_markdown_for_missing_canonical_core_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self._public_installation(root)
            core = root / "grill-harness"
            (core / "scripts" / "grh.py").unlink()
            contract = core / "references" / "入口内核契约.json"
            payload = json.loads(contract.read_text(encoding="utf-8"))
            payload["core"]["entry_check_script"] = "SKILL.md"
            contract.write_text(json.dumps(payload), encoding="utf-8")
            runner = FakeRunner(self._safe_cli_responses({"skills": entries}, {"skills": []}))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-plan",
            )

            installation = report["harness_installation"]
            self.assertFalse(report["entry_ready"])
            self.assertFalse(installation["contract_compatible"])
            self.assertEqual(installation["core_script"], "SKILL.md")
            self.assertEqual(installation["expected_core_script"], "scripts/grh.py")
            self.assertFalse(installation["core_script_verified"])

    def test_core_script_cannot_escape_through_symlinked_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self._public_installation(root)
            core = root / "grill-harness"
            shutil_target = root / "outside-scripts"
            shutil_target.mkdir()
            shutil_target.joinpath("grh.py").write_text("pass\n", encoding="utf-8")
            (core / "scripts" / "grh.py").unlink()
            (core / "scripts").rmdir()
            (core / "scripts").symlink_to(shutil_target, target_is_directory=True)
            runner = FakeRunner(self._safe_cli_responses({"skills": entries}, {"skills": []}))

            report = preflight.run_preflight(
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-plan",
            )

            self.assertFalse(report["entry_ready"])
            self.assertFalse(
                report["harness_installation"]["core_script_verified"]
            )

    def test_public_entries_use_cli_success_and_filesystem_fallback_for_failed_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self._public_installation(root)
            project_entries = entries[:4]
            global_entries = entries[4:]
            runner = FakeRunner({
                ("npx", "skills", "list", "--json"): {
                    "returncode": 0,
                    "stdout": json.dumps({"skills": project_entries}),
                },
                ("npx", "skills", "list", "-g", "--json"): {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "global unavailable",
                },
            })

            report = preflight.run_preflight(
                skill_roots={"global": [root]},
                runner=runner,
                check_harness_entries=True,
                invoking_entry="grh-start",
            )

            self.assertTrue(report["entry_ready"])
            scopes = {
                item["name"]: item["scope"]
                for item in report["harness_installation"]["entries"]
            }
            self.assertEqual(scopes["grill-harness"], "project")
            self.assertEqual(scopes["grh-upstream-check"], "global")
            self.assertFalse(report["actions_performed"])

    def test_cli_json_is_consulted_first_then_global_and_project_paths_are_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            global_skill = self._skill(root / "global", "grilling")
            project_skill = self._skill(root / "project", "domain-modeling")
            self._skill(root / "project", "grill-with-docs")
            codebase_skill = self._skill(root / "global", "codebase-design")
            runner = FakeRunner(self._safe_cli_responses(
                {"skills": [{"name": "domain-modeling", "path": str(project_skill)}]},
                {"skills": [
                    {"name": "grilling", "path": str(global_skill)},
                    {"name": "codebase-design", "path": str(codebase_skill)},
                ]},
            ))

            report = preflight.run_preflight(
                skill_roots=[root / "global", root / "project"], runner=runner
            )

            self.assertEqual(runner.calls[0], ["npx", "skills", "list", "--json"])
            self.assertEqual(runner.calls[1], ["npx", "skills", "list", "-g", "--json"])
            self.assertTrue(report["ready"])
            self.assertEqual(report["missing_required"], [])
            by_name = {item["name"]: item for item in report["capabilities"]}
            self.assertEqual(by_name["grilling"]["scope"], "global")
            self.assertEqual(by_name["domain-modeling"]["scope"], "project")
            self.assertTrue(all(item["verified"] for item in by_name.values() if item["required"]))

    def test_symlinks_are_resolved_and_metadata_name_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self._skill(root / "source", "grilling")
            install_root = root / "installed"
            install_root.mkdir()
            (install_root / "grilling").symlink_to(target, target_is_directory=True)
            bad = self._skill(install_root, "domain-modeling", metadata_name="wrong-name")
            self._skill(install_root, "codebase-design")
            runner = FakeRunner(self._safe_cli_responses({"skills": [
                    {"name": "grilling", "path": str(install_root / "grilling")},
                    {"name": "domain-modeling", "path": str(bad)},
                    {"name": "codebase-design", "path": str(install_root / "codebase-design")},
                ]}, {"skills": []}))

            report = preflight.run_preflight(skill_roots=[install_root], runner=runner)

            by_name = {item["name"]: item for item in report["capabilities"]}
            self.assertEqual(by_name["grilling"]["resolved_path"], str(target.resolve()))
            self.assertTrue(by_name["grilling"]["symlink"])
            self.assertFalse(by_name["domain-modeling"]["verified"])
            self.assertIn("domain-modeling", report["missing_required"])

    def test_missing_cli_falls_back_to_filesystem_but_never_invents_install_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in preflight.REQUIRED_CAPABILITIES:
                self._skill(root, name)
            runner = FakeRunner({
                ("npx", "skills", "list", "--json"): FileNotFoundError("npx"),
            })

            report = preflight.run_preflight(skill_roots={"global": [root]}, runner=runner)

            self.assertTrue(report["ready"])
            self.assertFalse(report["cli"]["available"])
            self.assertFalse(report["cli"]["complete"])
            self.assertEqual(report["install_commands"], [])
            self.assertTrue(all(item["scope"] == "global" for item in report["capabilities"] if item["verified"]))
            self.assertFalse(report["actions_performed"])

    def test_timed_out_scope_uses_filesystem_fallback_without_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in preflight.REQUIRED_CAPABILITIES:
                self._skill(root, name)
            runner = FakeRunner({
                ("npx", "skills", "list", "--json"): subprocess.TimeoutExpired(
                    ["npx", "skills", "list", "--json"], 20
                ),
                ("npx", "skills", "list", "-g", "--json"): {
                    "returncode": 0,
                    "stdout": json.dumps({"skills": []}),
                },
            })

            report = preflight.run_preflight(
                skill_roots={"project": [root]}, runner=runner
            )

            self.assertTrue(report["ready"])
            self.assertFalse(report["cli"]["complete"])
            self.assertIn("project", report["cli"]["error"])
            self.assertEqual(len(runner.calls), 2)

    def test_inventory_cache_skips_list_commands_but_rechecks_skill_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = [
                {"name": name, "path": str(self._skill(root, name))}
                for name in preflight.REQUIRED_CAPABILITIES
            ]
            cache_path = root / "cache" / "inventory.json"
            first_runner = FakeRunner(
                self._safe_cli_responses({"skills": entries}, {"skills": []})
            )

            first = preflight.run_preflight(
                runner=first_runner, cache_path=cache_path, now=1000
            )
            cached_runner = FakeRunner({})
            second = preflight.run_preflight(
                runner=cached_runner, cache_path=cache_path, now=1001
            )
            self.assertEqual(cached_runner.calls, [])
            shutil.rmtree(root / "grilling")
            stale = preflight.run_preflight(
                runner=cached_runner, cache_path=cache_path, now=1002
            )

            self.assertTrue(first["ready"])
            self.assertTrue(second["ready"])
            self.assertFalse(
                any(call[2:3] == ["list"] for call in cached_runner.calls)
            )
            self.assertFalse(stale["ready"])
            self.assertIn("grilling", stale["missing_required"])

            refresh_runner = FakeRunner(
                self._safe_cli_responses({"skills": entries}, {"skills": []})
            )
            preflight.run_preflight(
                runner=refresh_runner,
                cache_path=cache_path,
                now=1003,
                refresh_cache=True,
            )
            self.assertEqual(
                refresh_runner.calls[:2],
                [
                    ["npx", "skills", "list", "--json"],
                    ["npx", "skills", "list", "-g", "--json"],
                ],
            )

    def test_corrupt_or_expired_inventory_cache_falls_back_to_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = [
                {"name": name, "path": str(self._skill(root, name))}
                for name in preflight.REQUIRED_CAPABILITIES
            ]
            cache_path = root / "inventory.json"
            cache_path.write_text("not json", encoding="utf-8")
            corrupt_runner = FakeRunner(
                self._safe_cli_responses({"skills": entries}, {"skills": []})
            )

            corrupt = preflight.run_preflight(
                runner=corrupt_runner, cache_path=cache_path, now=1000
            )
            expired_runner = FakeRunner(
                self._safe_cli_responses({"skills": entries}, {"skills": []})
            )
            expired = preflight.run_preflight(
                runner=expired_runner, cache_path=cache_path, now=1601
            )

            self.assertTrue(corrupt["ready"])
            self.assertTrue(expired["ready"])
            self.assertEqual(len(corrupt_runner.calls), 2)
            self.assertEqual(len(expired_runner.calls), 2)

    def test_partial_cli_failure_preserves_successful_scope_and_uses_filesystem_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_skill = self._skill(root / "project", "domain-modeling")
            self._skill(root / "project", "grill-with-docs")
            global_root = root / "global"
            self._skill(global_root, "grilling")
            self._skill(global_root, "codebase-design")
            runner = FakeRunner({
                ("npx", "skills", "list", "--json"): {
                    "returncode": 0,
                    "stdout": json.dumps({
                        "skills": [{"name": "domain-modeling", "path": str(project_skill)}]
                    }),
                },
                ("npx", "skills", "list", "-g", "--json"): {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "global inventory unavailable",
                },
            })

            report = preflight.run_preflight(
                skill_roots={
                    "project": [root / "project"],
                    "global": [global_root],
                },
                runner=runner,
            )

            self.assertTrue(report["ready"])
            by_name = {item["name"]: item for item in report["capabilities"]}
            self.assertEqual(by_name["domain-modeling"]["scope"], "project")
            self.assertEqual(by_name["grilling"]["scope"], "global")
            self.assertFalse(by_name["grill-with-docs"]["verified"])
            self.assertTrue(report["cli"]["available"])
            self.assertFalse(report["cli"]["complete"])
            self.assertIn("global inventory unavailable", report["cli"]["error"])

    def test_missing_required_blocks_but_optional_and_reference_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._skill(root, "grilling")
            self._skill(root, "domain-modeling")
            payload = {"skills": [
                {"name": "grilling", "path": str(root / "grilling")},
                {"name": "domain-modeling", "path": str(root / "domain-modeling")},
            ]}
            runner = FakeRunner(self._safe_cli_responses(payload, {"skills": []}))

            report = preflight.run_preflight(
                skill_roots=[root], runner=runner, optional_capabilities=["requesting-code-review"]
            )

            self.assertFalse(report["ready"])
            self.assertEqual(report["missing_required"], ["codebase-design"])
            self.assertEqual(report["missing_optional"], ["requesting-code-review"])
            reference = next(item for item in report["capabilities"] if item["name"] == "grill-with-docs")
            self.assertEqual(reference["role"], "compatibility-reference")
            self.assertFalse(reference["callable_dependency"])
            self.assertEqual(len(report["install_commands"]), 1)
            self.assertIn("skills add mattpocock/skills", report["install_commands"][0])
            self.assertIn("codebase-design", report["install_commands"][0])
            self.assertIn("-g -a codex claude-code", report["install_commands"][0])
            self.assertIn("-y --copy", report["install_commands"][0])
            self.assertNotIn("requesting-code-review", report["install_commands"][0])
            self.assertEqual(
                report["update_commands"],
                ["npx skills update grilling domain-modeling codebase-design -g"],
            )
            self.assertNotIn(" add ", report["update_commands"][0])
            self.assertIn(" update ", report["update_commands"][0])
            self.assertFalse(any(call[2:3] in (["add"], ["update"]) for call in runner.calls))
            self.assertFalse(report["actions_performed"])
            self.assertFalse(report["accepted_upstream_changes"])

    def test_stale_cli_metadata_is_rejected_by_filesystem_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "removed" / "grilling"
            runner = FakeRunner(self._safe_cli_responses({"skills": [
                    {"name": "grilling", "path": str(missing)},
                ]}, {"skills": []}))

            report = preflight.run_preflight(skill_roots=[], runner=runner)

            grilling = next(item for item in report["capabilities"] if item["name"] == "grilling")
            self.assertEqual(grilling["status"], "stale-metadata")
            self.assertFalse(grilling["verified"])

    def test_successful_cli_inventory_is_not_augmented_from_unreported_filesystem_skills(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in preflight.REQUIRED_CAPABILITIES:
                self._skill(root, name)
            runner = FakeRunner(self._safe_cli_responses({"skills": []}, {"skills": []}))

            report = preflight.run_preflight(skill_roots={"project": [root]}, runner=runner)

            self.assertFalse(report["ready"])
            self.assertEqual(report["missing_required"], list(preflight.REQUIRED_CAPABILITIES))

    def test_metadata_name_in_body_is_not_accepted_without_yaml_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grilling"
            path.mkdir()
            path.joinpath("SKILL.md").write_text("# Notes\nname: grilling\n", encoding="utf-8")
            runner = FakeRunner(self._safe_cli_responses(
                {"skills": [{"name": "grilling", "path": str(path)}]}, {"skills": []}
            ))

            report = preflight.run_preflight(runner=runner)

            grilling = next(item for item in report["capabilities"] if item["name"] == "grilling")
            self.assertFalse(grilling["verified"])

    def test_ready_inventory_skips_top_level_help_and_update_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = []
            for name in preflight.REQUIRED_CAPABILITIES:
                path = self._skill(root, name)
                entries.append({"name": name, "path": str(path)})
            runner = FakeRunner(self._safe_cli_responses({"skills": entries}, {"skills": []}))

            report = preflight.run_preflight(runner=runner)

            self.assertEqual(report["install_commands"], [])
            self.assertEqual(report["update_commands"], [])
            self.assertNotIn(["npx", "skills", "--help"], runner.calls)
            self.assertFalse(any(call[2:3] in (["add"], ["update"]) for call in runner.calls))


if __name__ == "__main__":
    unittest.main()
