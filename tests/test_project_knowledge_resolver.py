import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
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

    def test_bootstrap_initializes_generic_project_knowledge_from_repo_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "admin-app"
            (project / "contracts").mkdir(parents=True)
            (project / "docs" / "plans").mkdir(parents=True)
            (project / ".codex" / "skills" / "admin-api-docs").mkdir(parents=True)
            (project / ".codex" / "agents").mkdir(parents=True)
            (project / "src" / "services").mkdir(parents=True)

            (project / "AGENTS.md").write_text(
                "# AGENTS.md\n\n"
                "## Hard Stops\n"
                "- Do not edit `src/services/**` without review.\n"
                "- Do not read `.env*` values.\n",
                encoding="utf-8",
            )
            (project / "contracts" / "project-context.yaml").write_text(
                "project_map:\n"
                "  guarded_paths:\n"
                "    - path: src/config/routes.tsx\n"
                "      reason: route registry\n",
                encoding="utf-8",
            )
            (project / "docs" / "project-map.md").write_text(
                "# 项目地图\n\n## 应用主干\n- `src/App.tsx`\n",
                encoding="utf-8",
            )
            (project / "docs" / "conventions.md").write_text(
                "# 开发约定\n\n## 验证 Gate\n- `pnpm lint`\n- `pnpm build`\n",
                encoding="utf-8",
            )
            (project / "docs" / "plans" / "2026-05-01-order-list.md").write_text(
                "# 订单列表计划\n\n## 目标\n优化筛选。\n",
                encoding="utf-8",
            )
            (project / ".codex" / "skills" / "admin-api-docs" / "SKILL.md").write_text(
                "---\nname: admin-api-docs\n---\n# API Docs\nUse before backend changes.\n",
                encoding="utf-8",
            )
            (project / ".codex" / "agents" / "implementer.toml").write_text(
                "role = \"coder\"\n",
                encoding="utf-8",
            )
            (project / "package.json").write_text(
                '{"dependencies":{"react":"^18.0.0"},"devDependencies":{"vite":"^5.0.0","typescript":"^5.0.0"},"scripts":{"lint":"eslint .","build":"vite build","test:unit":"vitest"}}',
                encoding="utf-8",
            )
            (project / ".api-spec.json").write_text(
                '{"paths":{"/v1/orders":{"get":{"summary":"must not be copied"}}}}',
                encoding="utf-8",
            )
            (project / ".env.local").write_text("TOKEN=secret\n", encoding="utf-8")

            wiki = LocalLlmWikiAdapter(root / "wiki")
            registry = ProjectRegistry(
                [
                    {
                        "name": "admin-app",
                        "aliases": ["后台"],
                        "path": str(project),
                        "keywords": ["订单"],
                    }
                ]
            )

            ProjectKnowledgeResolver.bootstrap_registry(wiki, registry)

            profile = wiki.read(wiki.find_by_kind("project_profile")[0]["id"])
            self.assertEqual(profile["project_id"], "admin-app")
            self.assertIn("package.json", profile["inventory_files"])
            self.assertEqual(profile["tech_stack"], [])
            self.assertEqual(profile["test_commands"], [])
            self.assertIn("Codex must classify technology stack", profile["body"])
            self.assertIn("AGENTS.md", profile["documentation_index"])
            self.assertIn(".codex/skills/admin-api-docs/SKILL.md", profile["codex_skills"])
            self.assertIn(".codex/agents/implementer.toml", profile["codex_agents"])
            self.assertIn(".api-spec.json", profile["external_sources"])
            self.assertIn(".env*", profile["guarded_paths"])
            self.assertIn("src/config/routes.tsx", profile["guarded_paths"])
            self.assertEqual(profile["source_refs"][0]["path"], "project-registry.json")
            self.assertTrue(any(ref.get("sha256") for ref in profile["source_refs"]))

            self.assertEqual(len(wiki.find_by_kind("project_guidance_contract")), 1)
            self.assertEqual(len(wiki.find_by_kind("project_architecture_map")), 1)
            self.assertEqual(len(wiki.find_by_kind("project_conventions")), 1)
            self.assertEqual(len(wiki.find_by_kind("verification_profile")), 1)
            self.assertEqual(len(wiki.find_by_kind("agent_tooling_profile")), 1)
            self.assertEqual(len(wiki.find_by_kind("historical_plan_index")), 1)

            external = wiki.read(wiki.find_by_kind("external_source_index")[0]["id"])
            self.assertEqual(external["status"], "candidate")
            self.assertEqual(external["freshness"]["mode"], "read_before_use")
            self.assertIn(".api-spec.json", external["body"])
            self.assertNotIn("/v1/orders", external["body"])
            overview = (root / "wiki" / "wiki" / "overview.md").read_text(encoding="utf-8")
            self.assertIn("## Project Initialization Writes", overview)
            self.assertIn("project=admin-app | kind=project_profile", overview)
            self.assertIn("path=wiki/entities/project-admin-app.md", overview)
            self.assertIn("path=wiki/concepts/project-admin-app-guidance.md", overview)
            self.assertIn("path=wiki/sources/project-admin-app-external-sources.md", overview)

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
