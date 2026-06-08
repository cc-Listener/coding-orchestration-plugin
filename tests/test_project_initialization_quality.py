import tempfile
import unittest
from pathlib import Path

from coding_orchestration.project_initialization_quality import evaluate_project_initialization_quality


class ProjectInitializationQualityTest(unittest.TestCase):
    def test_complete_bootstrap_contract_profile_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "admin"
            project.mkdir()
            profile = {
                "name": "admin",
                "documentation_index": [
                    "AGENTS.md",
                    "docs/project-map.md",
                    "docs/conventions.md",
                    "docs/component-contract.md",
                    "contracts/project-context.yaml",
                ],
                "test_commands": ["rtk pnpm test"],
                "external_sources": ["openapi.json", "figma.url"],
            }

            quality = evaluate_project_initialization_quality(project_path=project, profile=profile)

            self.assertEqual(quality.status, "complete")
            self.assertTrue(quality.has_guidance)
            self.assertTrue(quality.has_project_context)
            self.assertTrue(quality.has_component_contract)
            self.assertTrue(quality.has_verification_commands)
            self.assertEqual(quality.dynamic_source_count, 2)
            self.assertEqual(quality.missing, [])

    def test_missing_profile_reports_actionable_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "admin"
            project.mkdir()

            quality = evaluate_project_initialization_quality(project_path=project, profile={})

            self.assertEqual(quality.status, "missing")
            self.assertIn("guidance", quality.missing)
            self.assertIn("project_context", quality.missing)
            self.assertIn("component_contract", quality.missing)
            self.assertIn("verification_commands", quality.missing)

    def test_disk_files_can_fill_profile_gaps_without_writing_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "admin"
            (project / "docs").mkdir(parents=True)
            (project / "contracts").mkdir()
            (project / "AGENTS.md").write_text("rules\n", encoding="utf-8")
            (project / "docs" / "project-map.md").write_text("map\n", encoding="utf-8")
            (project / "contracts" / "project-context.yaml").write_text("name: admin\n", encoding="utf-8")

            quality = evaluate_project_initialization_quality(
                project_path=project,
                profile={"test_commands": ["rtk pytest -q"]},
            )

            self.assertEqual(quality.status, "complete")
            self.assertTrue(quality.has_guidance)
            self.assertTrue(quality.has_project_context)
            self.assertTrue(quality.has_component_contract)
            self.assertTrue(quality.has_verification_commands)


if __name__ == "__main__":
    unittest.main()
