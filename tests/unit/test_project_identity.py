import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import state


def run_git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def create_repository(path, remote=None):
    path.mkdir(parents=True)
    run_git(path, "init", "--quiet")
    run_git(path, "config", "user.email", "tests@example.com")
    run_git(path, "config", "user.name", "Grill Harness Tests")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    run_git(path, "add", "README.md")
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
        }
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--quiet", "-m", "initial"],
        check=True,
        capture_output=True,
        env=env,
    )
    if remote:
        run_git(path, "remote", "add", "origin", remote)
    return path


class ProjectIdentityTests(unittest.TestCase):
    def test_git_project_id_is_stable_when_head_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = create_repository(Path(temp_dir) / "project")
            before = state.identify_project(repo)

            (repo / "later.txt").write_text("later\n", encoding="utf-8")
            run_git(repo, "add", "later.txt")
            run_git(repo, "commit", "--quiet", "-m", "later")

            after = state.identify_project(repo)
            self.assertEqual(before.project_id, after.project_id)
            self.assertEqual(before.directory_name, after.directory_name)

    def test_same_named_repositories_are_kept_separate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = create_repository(Path(temp_dir) / "one" / "project")
            second = create_repository(Path(temp_dir) / "two" / "project")

            first_identity = state.identify_project(first)
            second_identity = state.identify_project(second)

            self.assertNotEqual(first_identity.project_id, second_identity.project_id)
            self.assertNotEqual(first_identity.directory_name, second_identity.directory_name)
            self.assertTrue(first_identity.directory_name.startswith("project--"))

    def test_relocated_repository_keeps_a_shared_candidate_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original = create_repository(
                Path(temp_dir) / "original" / "project",
                "git@github.com:Example/Project.git",
            )
            original_identity = state.identify_project(original)
            relocated = Path(temp_dir) / "relocated" / "project"
            relocated.parent.mkdir(parents=True)
            original.rename(relocated)

            relocated_identity = state.identify_project(relocated)

            self.assertNotEqual(original_identity.project_id, relocated_identity.project_id)
            self.assertTrue(
                set(original_identity.relocation_candidates)
                & set(relocated_identity.relocation_candidates)
            )

    def test_non_git_project_uses_its_normalized_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "notes"
            project.mkdir()

            identity = state.identify_project(project / ".")

            self.assertFalse(identity.is_git)
            self.assertEqual(identity.normalized_path, str(project.resolve()))
            self.assertEqual(identity.relocation_candidates, ())
            self.assertTrue(identity.directory_name.startswith("notes--"))

    def test_workflow_names_are_human_readable_and_isolated(self):
        first = state.workflow_directory_name("发布检查", "project-123", "workflow-1")
        second = state.workflow_directory_name("发布检查", "project-123", "workflow-2")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("发布检查--"))
        self.assertEqual(first, state.workflow_directory_name("发布检查", "project-123", "workflow-1"))


if __name__ == "__main__":
    unittest.main()
