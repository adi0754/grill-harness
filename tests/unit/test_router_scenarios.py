import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER_DIR = REPO_ROOT / "tests" / "scenarios" / "router"


class RouterScenarioEvidenceTests(unittest.TestCase):
    def test_router_recommends_public_entry_without_initializing(self):
        router = (REPO_ROOT / "skills" / "grill-harness" / "SKILL.md").read_text(encoding="utf-8")

        self.assertNotIn("grh> init --project", router)
        self.assertIn("entry-check --entry <公开入口>", router)
        self.assertIn("Router 本身不初始化", router)

    def test_final_green_evidence_uses_grh_for_every_route(self):
        green = (ROUTER_DIR / "GREEN.md").read_text(encoding="utf-8")
        sections = {
            name: green.split("## `{}`".format(name), 1)[1].split("\n## ", 1)[0]
            for name in (
                "start.md",
                "continue.md",
                "status.md",
                "recovery.md",
                "upstream-check.md",
            )
        }

        for name, section in sections.items():
            with self.subTest(name=name):
                self.assertIn("scripts/grh.py", section)
                self.assertIn("GRILL_HARNESS_TEST_ROOT", section)
                self.assertIn("Exit code", section)
                self.assertIn("JSON summary", section)
                self.assertIn("Fresh-context answer", section)

        for name in ("start.md", "continue.md", "status.md", "recovery.md"):
            self.assertIn('"$GRH" status --project', sections[name])
        self.assertIn(
            '"$GRH" upstream-check --previous',
            sections["upstream-check.md"],
        )

    def test_reproducible_router_fixtures_exist(self):
        fixtures = ROUTER_DIR / "fixtures"
        for name in (
            "continue-state.yaml",
            "status-state.yaml",
            "recovery-state.yaml",
            "previous-manifest.json",
            "upstream-facts.json",
        ):
            with self.subTest(name=name):
                self.assertTrue((fixtures / name).is_file())

    def test_committed_router_evidence_does_not_expose_personal_paths(self):
        green = (ROUTER_DIR / "GREEN.md").read_text(encoding="utf-8")

        self.assertNotIn("/Users/", green)
        self.assertNotIn("/home/", green)
        self.assertNotIn("/tmp/grh-router-", green)


if __name__ == "__main__":
    unittest.main()
