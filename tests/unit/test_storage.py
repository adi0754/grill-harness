import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import common


class StorageRootTests(unittest.TestCase):
    def test_default_root_is_under_the_users_home_directory(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(common.Path, "home", return_value=Path(home)):
                    self.assertEqual(
                        common.resolve_storage_root(),
                        Path(home).resolve() / ".grill-harness",
                    )

    def test_explicit_test_root_override_wins_over_the_default(self):
        with tempfile.TemporaryDirectory() as test_root:
            with mock.patch.dict(
                os.environ,
                {common.TEST_STORAGE_ROOT_ENV: test_root},
                clear=True,
            ):
                self.assertEqual(common.resolve_storage_root(), Path(test_root).resolve())

    def test_storage_layout_creates_required_chinese_directories(self):
        with tempfile.TemporaryDirectory() as test_root:
            paths = common.ensure_storage_layout(Path(test_root))

            self.assertEqual(set(paths), {"projects", "workflows", "backups"})
            self.assertEqual(
                {path.name for path in paths.values()},
                {"项目", "工作流", "备份"},
            )
            self.assertTrue(all(path.is_dir() for path in paths.values()))

    def test_destructive_schema_migration_gets_a_backup_first(self):
        with tempfile.TemporaryDirectory() as test_root:
            state_file = Path(test_root) / "state.yaml"
            state_file.write_text('{"schema_version": 1}', encoding="utf-8")

            backup = common.backup_before_schema_migration(
                state_file,
                Path(test_root) / "备份",
            )

            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_bytes(), state_file.read_bytes())
            self.assertNotEqual(backup, state_file)


if __name__ == "__main__":
    unittest.main()
