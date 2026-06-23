import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.project.project_knowledge_initializer import ProjectKnowledgeInitializer
from coding_orchestration.project.project_resolver import Project


class ProjectKnowledgeInitializerTest(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp_dir.name)

    def tearDown(self):
        self._temp_dir.cleanup()

    def test_initializer_records_inventory_without_final_tech_stack_claims(self):
        root = self.temp_path / "repo"
        root.mkdir()
        (root / "package.json").write_text(
            json.dumps({"dependencies": {"react": "latest"}, "scripts": {"test": "vitest"}}),
            encoding="utf-8",
        )
        project = Project(name="demo", path=str(root))

        docs = ProjectKnowledgeInitializer().build_documents(project)
        profile = next(doc for doc in docs if doc["kind"] == "project_profile")

        self.assertIn("package.json", profile["inventory_files"])
        self.assertEqual(profile["tech_stack"], [])
        self.assertIn("Codex must classify technology stack", profile["body"])

    def test_inventory_files_do_not_expose_exact_sensitive_env_file_names(self):
        root = self.temp_path / "repo"
        root.mkdir()
        (root / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest"}}),
            encoding="utf-8",
        )
        (root / ".env.local").write_text("TOKEN=secret\n", encoding="utf-8")
        project = Project(name="demo", path=str(root))

        docs = ProjectKnowledgeInitializer().build_documents(project)
        profile = next(doc for doc in docs if doc["kind"] == "project_profile")

        self.assertIn("package.json", profile["inventory_files"])
        self.assertNotIn(".env.local", profile["inventory_files"])
        self.assertNotIn(".env.local", "\n".join(profile["inventory_files"]))


if __name__ == "__main__":
    unittest.main()
