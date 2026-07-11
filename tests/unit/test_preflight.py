import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
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
                "stdout": "Usage: skills <command>\n  add <source> --skill <skills...>\n",
            },
        }

    def test_cli_json_is_consulted_first_then_global_and_project_paths_are_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            global_skill = self._skill(root / "global", "grilling")
            project_skill = self._skill(root / "project", "domain-modeling")
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
            self.assertEqual(report["install_commands"], [])
            self.assertTrue(all(item["scope"] == "global" for item in report["capabilities"] if item["verified"]))
            self.assertFalse(report["actions_performed"])

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
            self.assertNotIn("requesting-code-review", report["install_commands"][0])
            self.assertEqual(report["update_commands"], report["install_commands"])
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


if __name__ == "__main__":
    unittest.main()
