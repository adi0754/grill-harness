import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "tests" / "scenarios" / "runtime_safety.py"
RESULTS = REPO_ROOT / "tests" / "scenarios" / "results"


def load_helper(testcase):
    if not HELPER.is_file():
        testcase.fail("runtime_safety.py is required")
    spec = importlib.util.spec_from_file_location("runtime_safety", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeEnvironmentSafetyTests(unittest.TestCase):
    def test_minimal_environment_drops_injected_model_and_cloud_credentials(self):
        safety = load_helper(self)
        injected = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C",
            "TMPDIR": "/tmp/source",
            "OPENAI_API_KEY": "fake-openai",
            "OPENAI_ORG_ID": "fake-org",
            "ANTHROPIC_API_KEY": "fake-anthropic",
            "CLAUDE_CODE_OAUTH_TOKEN": "fake-claude",
            "AWS_ACCESS_KEY_ID": "fake-aws-key",
            "AWS_SECRET_ACCESS_KEY": "fake-aws-secret",
            "AWS_SESSION_TOKEN": "fake-aws-session",
            "BEDROCK_API_KEY": "fake-bedrock",
            "GOOGLE_APPLICATION_CREDENTIALS": "/fake/google.json",
            "VERTEX_PROJECT_ID": "fake-vertex",
            "AZURE_OPENAI_API_KEY": "fake-azure",
            "UNRELATED_SECRET": "must-not-be-inherited",
        }
        result = safety.minimal_environment(
            injected,
            home="/isolated/home",
            temp_dir="/isolated/tmp",
            extra={"CODEX_HOME": "/isolated/home/.codex"},
        )
        self.assertEqual(
            set(result),
            {"PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "CODEX_HOME"},
        )
        self.assertEqual(result["HOME"], "/isolated/home")
        self.assertEqual(result["TMPDIR"], "/isolated/tmp")
        self.assertFalse(any("fake" in value for value in result.values()))

    def test_environment_cli_does_not_inherit_injected_credentials(self):
        load_helper(self)
        env = os.environ.copy()
        env.update(
            {
                "OPENAI_API_KEY": "fake-openai",
                "ANTHROPIC_API_KEY": "fake-anthropic",
                "AWS_SESSION_TOKEN": "fake-session",
                "BEDROCK_API_KEY": "fake-bedrock",
                "GOOGLE_APPLICATION_CREDENTIALS": "/fake/google.json",
                "VERTEX_PROJECT_ID": "fake-vertex",
                "AZURE_OPENAI_API_KEY": "fake-azure",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "env-json",
                "--home",
                "/isolated/home",
                "--temp-dir",
                "/isolated/tmp",
                "--set",
                "CODEX_HOME=/isolated/home/.codex",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        child_env = json.loads(completed.stdout)
        self.assertFalse(any("fake" in value for value in child_env.values()))
        self.assertNotIn("OPENAI_API_KEY", child_env)
        self.assertNotIn("AWS_SESSION_TOKEN", child_env)

    def test_exec_environment_scrubs_credentials_before_starting_child(self):
        load_helper(self)
        env = os.environ.copy()
        env.update(
            {
                "OPENAI_API_KEY": "fake-openai",
                "ANTHROPIC_API_KEY": "fake-anthropic",
                "AWS_ACCESS_KEY_ID": "fake-aws",
                "AWS_SESSION_TOKEN": "fake-session",
                "BEDROCK_API_KEY": "fake-bedrock",
                "GOOGLE_APPLICATION_CREDENTIALS": "/fake/google.json",
                "VERTEX_PROJECT_ID": "fake-vertex",
                "AZURE_OPENAI_API_KEY": "fake-azure",
            }
        )
        child = "import json, os; print(json.dumps(dict(os.environ), sort_keys=True))"
        completed = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "exec-env",
                "--home",
                "/isolated/home",
                "--temp-dir",
                "/isolated/tmp",
                "--set",
                "CODEX_HOME=/isolated/home/.codex",
                "--",
                sys.executable,
                "-c",
                child,
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        child_env = json.loads(completed.stdout)
        self.assertFalse(any("fake" in value for value in child_env.values()))
        self.assertTrue(
            {"PATH", "HOME", "TMPDIR", "CODEX_HOME"}.issubset(child_env)
        )
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AWS_ACCESS_KEY_ID",
            "AWS_SESSION_TOKEN",
            "BEDROCK_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "VERTEX_PROJECT_ID",
            "AZURE_OPENAI_API_KEY",
        ):
            self.assertNotIn(name, child_env)


class RuntimeEvidenceSanitizationTests(unittest.TestCase):
    def test_sanitizer_normalizes_runtime_correlation_metadata_and_temp_root(self):
        safety = load_helper(self)
        raw = (
            'thread_id="019f52d6-fe75-7d01-957f-653facc1e274" '
            'session_id=550e8400-e29b-41d4-a716-446655440000 '
            'uuid: 123e4567-e89b-12d3-a456-426614174000 '
            'request id: req_909a56bdd1b648e8943fc13999aac203 '
            'cf-ray: a19a838e790fb4cd-SIN '
            'OPENAI_API_KEY=sk-test-secret-value '
            '/tmp/grh-runtime.ABC123/home'
        )
        sanitized = safety.sanitize_runtime_text(raw, temp_root="/tmp/grh-runtime.ABC123")
        self.assertIn("<THREAD_ID>", sanitized)
        self.assertIn("<SESSION_ID>", sanitized)
        self.assertIn("<UUID>", sanitized)
        self.assertIn("request id: <REQUEST_ID>", sanitized)
        self.assertIn("cf-ray: <CF_RAY>", sanitized)
        self.assertIn("OPENAI_API_KEY=<REDACTED>", sanitized)
        self.assertIn("<TEMP_ROOT>/home", sanitized)
        for token in (
            "019f52d6-fe75-7d01-957f-653facc1e274",
            "550e8400-e29b-41d4-a716-446655440000",
            "123e4567-e89b-12d3-a456-426614174000",
            "req_909a56bdd1b648e8943fc13999aac203",
            "a19a838e790fb4cd-SIN",
            "sk-test-secret-value",
            "/tmp/grh-runtime.ABC123",
        ):
            self.assertNotIn(token, sanitized)

    def test_committed_runtime_results_have_no_sensitive_correlation_metadata(self):
        patterns = {
            "uuid": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I),
            "request_id": re.compile(r"\breq_[A-Za-z0-9]+\b"),
            "cf_ray": re.compile(r"\b[0-9a-f]{16,}-[A-Z]{3}\b"),
            "temp_root": re.compile(r"/(?:private/)?var/folders/[^\s\"']+/grh-(?:codex|claude)[.-][^/\s\"']+"),
            "credential_value": re.compile(
                r"(?i)\b(?:OPENAI_[A-Z_]*KEY|ANTHROPIC_[A-Z_]*(?:KEY|TOKEN)|"
                r"CLAUDE_[A-Z_]*(?:KEY|TOKEN)|AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)|"
                r"BEDROCK_[A-Z_]*(?:KEY|TOKEN)|GOOGLE_APPLICATION_CREDENTIALS|"
                r"VERTEX_[A-Z_]+|AZURE_[A-Z_]*(?:KEY|TOKEN))\b\s*[:=]\s*[\"']?(?:fake-|sk-|AKIA|[A-Za-z0-9_/.-]{12,})"
            ),
        }
        violations = []
        for path in RESULTS.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for name, pattern in patterns.items():
                if pattern.search(text):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{name}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
