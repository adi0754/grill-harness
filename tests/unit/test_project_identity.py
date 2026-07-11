import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
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
            self.assertEqual(
                first_identity.directory_name,
                "project-{}".format(first_identity.project_id[:8]),
            )

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
            self.assertEqual(
                identity.directory_name,
                "notes-{}".format(identity.project_id[:8]),
            )

    def test_workflow_names_are_human_readable_and_isolated(self):
        created_on = date(2026, 7, 12)
        first = state.workflow_directory_name(
            "发布检查", "project-123", "workflow-1", created_on
        )
        second = state.workflow_directory_name(
            "发布检查", "project-123", "workflow-2", created_on
        )

        self.assertNotEqual(first, second)
        self.assertEqual(
            first,
            "{}-发布检查-{}".format(
                created_on.isoformat(),
                state.workflow_id("project-123", "workflow-1")[:8],
            ),
        )
        self.assertEqual(
            first,
            state.workflow_directory_name(
                "发布检查", "project-123", "workflow-1", created_on
            ),
        )

    def test_relative_local_remote_is_resolved_from_repository_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            repo = create_repository(base / "work" / "project", "../origin.git")
            unrelated_cwd = base / "elsewhere"
            unrelated_cwd.mkdir()
            previous_cwd = Path.cwd()
            try:
                os.chdir(str(unrelated_cwd))
                identity = state.identify_project(repo)
            finally:
                os.chdir(str(previous_cwd))

            self.assertEqual(
                identity.normalized_remote,
                "file://{}".format((base / "work" / "origin.git").resolve()),
            )

    def test_project_id_does_not_change_when_switching_between_history_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = create_repository(Path(temp_dir) / "project")
            original_branch = run_git(repo, "branch", "--show-current")
            run_git(repo, "checkout", "--quiet", "--orphan", "alternate-root")
            run_git(repo, "rm", "--quiet", "-rf", ".")
            (repo / "alternate.txt").write_text("alternate\n", encoding="utf-8")
            run_git(repo, "add", "alternate.txt")
            run_git(repo, "commit", "--quiet", "-m", "alternate root")

            alternate_identity = state.identify_project(repo)
            run_git(repo, "checkout", "--quiet", original_branch)
            original_identity = state.identify_project(repo)

            self.assertEqual(alternate_identity.project_id, original_identity.project_id)
            self.assertEqual(
                alternate_identity.history_roots,
                original_identity.history_roots,
            )
            self.assertEqual(len(original_identity.history_roots), 2)

    def test_windows_paths_are_normalized_without_using_the_process_cwd(self):
        self.assertEqual(
            state.normalize_project_path(r"C:\Users\Alice\Project\..\Repo"),
            r"c:\users\alice\repo",
        )

    def test_windows_relative_remote_is_resolved_from_repository_root(self):
        self.assertEqual(
            state.normalize_git_remote(
                r"..\origin.git",
                r"C:\work\project",
            ),
            r"file://c:\work\origin.git",
        )

    def test_windows_drive_remote_is_local_not_scp_syntax(self):
        self.assertEqual(
            state.normalize_git_remote(r"C:\repos\origin.git"),
            r"file://c:\repos\origin.git",
        )

    def test_windows_unc_file_remote_keeps_its_server_and_share(self):
        file_url = state.normalize_git_remote("file://Server/Share/origin.git")
        native_unc = state.normalize_git_remote(r"\\Server\Share\origin.git")

        self.assertEqual(file_url, "file://server/share/origin.git")
        self.assertEqual(native_unc, file_url)

    def test_localhost_file_remote_preserves_posix_path_case(self):
        upper = state.normalize_git_remote(
            "file://localhost/tmp/CaseSensitive.git"
        )
        lower = state.normalize_git_remote(
            "file://localhost/tmp/casesensitive.git"
        )

        self.assertEqual(
            upper,
            "file://{}".format(Path("/tmp/CaseSensitive.git").resolve()),
        )
        self.assertEqual(
            lower,
            "file://{}".format(Path("/tmp/casesensitive.git").resolve()),
        )
        self.assertNotEqual(upper, lower)

    def test_windows_project_directory_uses_only_the_basename(self):
        identity = state.identify_project(r"C:\Users\Alice\Repo")

        self.assertEqual(
            identity.directory_name,
            "repo-{}".format(identity.project_id[:8]),
        )

    def test_directory_names_remove_windows_forbidden_characters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / 'bad:name*?"<>|'
            project.mkdir()

            identity = state.identify_project(project)

            self.assertEqual(
                identity.directory_name,
                "bad-name-{}".format(identity.project_id[:8]),
            )
            self.assertFalse(set('<>:"/\\|?*') & set(identity.directory_name))

    def test_directory_names_guard_reserved_windows_devices_with_extensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "CON.txt"
            project.mkdir()

            identity = state.identify_project(project)

            self.assertEqual(
                identity.directory_name,
                "_CON.txt-{}".format(identity.project_id[:8]),
            )


if __name__ == "__main__":
    unittest.main()
