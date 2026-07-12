import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO_ROOT / "tests" / "scenarios" / "codex"
RESULTS_DIR = REPO_ROOT / "tests" / "scenarios" / "results" / "codex-0.144.0-alpha.4"


class CodexScenarioEvidenceTests(unittest.TestCase):
    def test_all_required_contexts_are_defined(self):
        scenarios = json.loads((SCENARIO_DIR / "scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [item["id"] for item in scenarios],
            [
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
            ],
        )
        self.assertTrue(all(item["applicable"] for item in scenarios))

    def test_runner_enforces_isolation_without_copying_credentials(self):
        runner = (SCENARIO_DIR / "run.sh").read_text(encoding="utf-8")
        for marker in (
            '--set "CODEX_HOME=$TMP/home/.codex"',
            '--set "GRILL_HARNESS_TEST_ROOT=$TMP/runtime"',
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox read-only",
            'runtime_safety.py',
            'exec-env',
            'sanitize-file',
            '--repo-root "$REPO"',
            '--fixture-root "$HERE/fixtures"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, runner)
        self.assertNotIn("auth.json", runner)

    def test_unverified_result_does_not_claim_runtime_pass(self):
        score = (RESULTS_DIR / "SCORE.md").read_text(encoding="utf-8")
        self.assertIn("unverified", score)
        self.assertIn("Missing bearer or basic authentication", score)
        self.assertNotIn("| PASS |", score)
        scenarios = json.loads((SCENARIO_DIR / "scenarios.json").read_text(encoding="utf-8"))
        for item in scenarios[:8]:
            self.assertTrue((RESULTS_DIR / "final" / f'{item["id"]}.md').is_file())
            self.assertEqual(
                (RESULTS_DIR / "raw" / f'{item["id"]}.exit').read_text(encoding="utf-8").strip(),
                "UNVERIFIED",
            )
        self.assertIn("additional V2 scenarios", score)
        self.assertIn("definition-only and unverified", score)
        for item in scenarios[8:]:
            self.assertFalse((RESULTS_DIR / "final" / f'{item["id"]}.md').exists())
        self.assertEqual(
            (RESULTS_DIR / "raw" / "startup-prompt.exit").read_text(encoding="utf-8").strip(),
            "UNVERIFIED",
        )


if __name__ == "__main__":
    unittest.main()
