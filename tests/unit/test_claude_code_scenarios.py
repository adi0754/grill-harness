import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO_ROOT / "tests" / "scenarios" / "claude-code"
RESULTS_DIR = REPO_ROOT / "tests" / "scenarios" / "results" / "claude-code"


class ClaudeCodeScenarioEvidenceTests(unittest.TestCase):
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
