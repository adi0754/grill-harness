import unittest
from unittest import mock
import os
from pathlib import Path
import importlib.util
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO_ROOT / "tests" / "scenarios" / "claude-code"
RESULTS_DIR = REPO_ROOT / "tests" / "scenarios" / "results" / "claude-code"


class ClaudeCodeScenarioEvidenceTests(unittest.TestCase):
    def test_isolated_environment_drops_injected_credentials(self):
        spec = importlib.util.spec_from_file_location("claude_scenarios", SCENARIO_DIR / "run.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        injected = {
            "PATH": "/usr/bin:/bin",
            "OPENAI_API_KEY": "fake-openai",
            "ANTHROPIC_API_KEY": "fake-anthropic",
            "CLAUDE_CODE_OAUTH_TOKEN": "fake-claude",
            "AWS_SESSION_TOKEN": "fake-session",
            "BEDROCK_API_KEY": "fake-bedrock",
            "GOOGLE_APPLICATION_CREDENTIALS": "/fake/google.json",
            "VERTEX_PROJECT_ID": "fake-vertex",
            "AZURE_OPENAI_API_KEY": "fake-azure",
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, injected, clear=True):
            result = runner.isolated_env(Path(directory))
        self.assertFalse(any("fake" in value for value in result.values()))
        self.assertNotIn("OPENAI_API_KEY", result)
        self.assertNotIn("AWS_SESSION_TOKEN", result)

    def test_all_required_contexts_are_defined(self):
        scenarios = (
            "light-bug",
            "standard-feature",
            "route-choice",
            "repository-challenge",
            "interrupted-recovery",
            "unsafe-parallelism",
            "missing-evidence",
            "upstream-change",
            "requirement-only-scope",
            "non-recommended-route",
            "review-only",
            "unaccepted-archive",
            "third-repeated-failure",
            "route-failure-reselection",
            "knowledge-reuse",
            "upstream-read-only",
            "human-first-artifacts",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                self.assertTrue((SCENARIO_DIR / f"{scenario}.prompt.md").is_file())
                self.assertTrue((SCENARIO_DIR / f"{scenario}.expected.md").is_file())

    def test_runner_enforces_isolation(self):
        runner = (SCENARIO_DIR / "run.py").read_text(encoding="utf-8")
        for marker in (
            '"HOME": str(home)',
            '"CLAUDE_CONFIG_DIR": str(home / ".claude")',
            '"GRILL_HARNESS_TEST_ROOT": str(home / ".grill-harness")',
            '"--no-session-persistence"',
            "make_read_only(project)",
            "minimal_environment",
            "sanitize_runtime_text",
            "repo_root=str(repo_root)",
            "fixture_root=str(project)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)

    def test_results_do_not_claim_an_unverified_runtime_pass(self):
        summary_path = RESULTS_DIR / "SUMMARY.md"
        if not summary_path.is_file():
            self.skipTest("runtime evidence has not been generated")
        summary = summary_path.read_text(encoding="utf-8")
        self.assertIn("未验证", summary)
        self.assertIn("Not logged in", summary)
        self.assertNotIn("| PASS |", summary)
        self.assertIn("additional V2 scenarios", summary)
        self.assertIn("definition-only and unverified", summary)

        for scenario in (
            "light-bug",
            "standard-feature",
            "route-choice",
            "repository-challenge",
            "interrupted-recovery",
            "unsafe-parallelism",
            "missing-evidence",
            "upstream-change",
        ):
            with self.subTest(scenario=scenario):
                result_dir = RESULTS_DIR / scenario
                for name in (
                    "auth-status.json",
                    "claude-version.txt",
                    "command.txt",
                    "environment.txt",
                    "expected.md",
                    "git-baseline.txt",
                    "git-status.txt",
                    "prompt.md",
                    "result.md",
                    "stderr.txt",
                    "stdout.json",
                    "task-package.md",
                ):
                    self.assertTrue((result_dir / name).is_file())


if __name__ == "__main__":
    unittest.main()
