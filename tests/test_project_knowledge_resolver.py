import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_knowledge_resolver import ProjectKnowledgeResolver
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class ProjectKnowledgeResolverTest(unittest.TestCase):
    def test_resolves_project_profile_from_llm_wiki_without_registry_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = LocalLlmWikiAdapter(Path(tmp) / "wiki")
            wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": "CRM Admin 项目画像",
                    "body": "CRM后台，客户列表模块。",
                    "project": "crm-admin",
                    "project_id": "crm-admin",
                    "name": "crm-admin",
                    "aliases": ["CRM后台"],
                    "local_paths": ["/repo/crm-admin"],
                    "modules": [
                        {
                            "name": "客户列表",
                            "keywords": ["客户列表", "客户筛选"],
                            "paths": ["src/customer"],
                        }
                    ],
                    "test_commands": ["rtk pnpm test"],
                    "status": "verified",
                },
                options={"dedupe_key": "project:crm-admin"},
            )
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )

            result = resolver.resolve("CRM后台有个需求，客户列表新增状态筛选")

            self.assertFalse(result.needs_human)
            self.assertEqual(result.project_name, "crm-admin")
            self.assertEqual(result.project_path, "/repo/crm-admin")
            self.assertEqual(result.match_evidence[0].source, "llm_wiki")

    def test_bootstraps_registry_projects_into_llm_wiki_project_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = LocalLlmWikiAdapter(Path(tmp) / "wiki")
            registry = ProjectRegistry(
                [
                    {
                        "name": "order-system",
                        "aliases": ["订单系统"],
                        "path": "/repo/order",
                        "keywords": ["发货"],
                        "default_test_commands": ["rtk pnpm test"],
                    }
                ]
            )

            ProjectKnowledgeResolver.bootstrap_registry(wiki, registry)

            docs = wiki.find_by_kind("project_profile")
            self.assertEqual(len(docs), 1)
            loaded = wiki.read(docs[0]["id"])
            self.assertEqual(loaded["project_id"], "order-system")
            self.assertEqual(loaded["local_paths"], ["/repo/order"])
            self.assertEqual(loaded["status"], "verified")

    def test_wiki_project_profile_supplies_workflow_constraints_without_registry_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "crm-admin"
            project.mkdir()
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": "CRM Admin 项目画像",
                    "body": "CRM后台 客户列表",
                    "project": "crm-admin",
                    "name": "crm-admin",
                    "aliases": ["CRM后台"],
                    "path": str(project),
                    "keywords": ["客户列表"],
                    "allowed_paths": ["src/customer"],
                    "forbidden_paths": [".env", "deploy/"],
                    "test_commands": ["rtk pnpm test:crm"],
                    "default_runner": "codex_cli",
                    "status": "verified",
                },
                options={"dedupe_key": "project:crm-admin"},
            )
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            orchestrator = CodingOrchestrator(
                ledger=TaskLedger(root / "ledger.db"),
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )

            workflow = orchestrator._workflow_for_project(project.resolve())

            self.assertEqual(workflow.allowed_paths, ["src/customer"])
            self.assertEqual(workflow.forbidden_paths, [".env", "deploy/"])
            self.assertEqual(workflow.default_test_commands, ["rtk pnpm test:crm"])
            self.assertEqual(workflow.recommended_runner, "codex_cli")


if __name__ == "__main__":
    unittest.main()
