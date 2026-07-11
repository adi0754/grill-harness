import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import common


class AtomicWriteTests(unittest.TestCase):
    def test_json_compatible_yaml_round_trip_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "状态.yaml"
            payload = {
                "schema_version": 1,
                "项目": "烧烤流程",
                "steps": ["准备", "审查"],
                "active": True,
            }

            common.atomic_write_yaml(destination, payload)

            self.assertEqual(common.read_yaml(destination), payload)
            self.assertIn("烧烤流程", destination.read_text(encoding="utf-8"))

    def test_interrupted_replace_preserves_previous_file_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "state.yaml"
            common.atomic_write_yaml(destination, {"version": 1})
            previous_bytes = destination.read_bytes()

            with mock.patch.object(common.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    common.atomic_write_yaml(destination, {"version": 2})

            self.assertEqual(destination.read_bytes(), previous_bytes)
            self.assertEqual(list(Path(temp_dir).glob(".state.yaml.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
