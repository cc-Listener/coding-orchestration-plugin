from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.project_profile_catalog import ProjectProfileCatalog
from coding_orchestration.project_resolver import Project


class FakeWiki:
    def __init__(self, docs: list[dict]):
        self.docs = {str(doc.get("id") or index): doc for index, doc in enumerate(docs)}

    def find_by_kind(self, kind: str, filters: dict | None = None) -> list[dict]:
        filters = filters or {}
        refs = []
        for doc_id, doc in self.docs.items():
            if doc.get("kind") != kind:
                continue
            if any(doc.get(key) != value for key, value in filters.items()):
                continue
            refs.append({"id": doc_id})
        return refs

    def read(self, ref_id: str) -> dict | None:
        return self.docs.get(ref_id)


class ProjectProfileCatalogTest(unittest.TestCase):
    def test_known_profiles_merges_wiki_profiles_and_registry_fallback(self):
        wiki = FakeWiki(
            [
                {
                    "id": "profile_1",
                    "kind": "project_profile",
                    "name": "order",
                    "project": "order",
                    "aliases": ["订单"],
                    "local_paths": ["/repo/order"],
                    "status": "verified",
                    "updated_at": "2026-06-01T00:00:00Z",
                }
            ]
        )
        catalog = ProjectProfileCatalog(
            wiki=wiki,
            registry_projects=lambda: [
                Project(name="order", path="/registry/order", aliases=("旧订单",)),
                Project(name="billing", path="/repo/billing", aliases=("账单",)),
            ],
        )

        profiles = catalog.known_profiles()

        self.assertEqual([profile["name"] for profile in profiles], ["billing", "order"])
        self.assertEqual(profiles[0]["source"], "project_registry")
        self.assertEqual(profiles[0]["aliases"], ["账单"])
        self.assertEqual(profiles[1]["source"], "llm_wiki")
        self.assertEqual(profiles[1]["path"], "/repo/order")

    def test_find_matches_name_alias_project_or_path_basename(self):
        wiki = FakeWiki(
            [
                {
                    "id": "profile_1",
                    "kind": "project_profile",
                    "name": "order-admin",
                    "project": "order",
                    "aliases": ["订单后台"],
                    "local_paths": ["/repo/order-admin"],
                    "status": "verified",
                }
            ]
        )
        catalog = ProjectProfileCatalog(wiki=wiki, registry_projects=lambda: [])

        self.assertEqual(catalog.find("order-admin")["name"], "order-admin")
        self.assertEqual(catalog.find("订单后台")["name"], "order-admin")
        self.assertEqual(catalog.find("order")["name"], "order-admin")
        self.assertEqual(catalog.find("order-admin")["path"], "/repo/order-admin")
        self.assertIsNone(catalog.find("missing"))

    def test_format_list_marks_active_project_and_includes_aliases_and_updated_at(self):
        wiki = FakeWiki(
            [
                {
                    "id": "profile_1",
                    "kind": "project_profile",
                    "name": "order",
                    "aliases": ["订单"],
                    "local_paths": ["/repo/order"],
                    "status": "verified",
                    "updated_at": "2026-06-01T00:00:00Z",
                }
            ]
        )
        catalog = ProjectProfileCatalog(wiki=wiki, registry_projects=lambda: [])

        message = catalog.format_list(active_project={"name": "order"})

        self.assertIn("当前已知项目", message)
        self.assertIn("order（当前）", message)
        self.assertIn("别名: 订单", message)
        self.assertIn("更新时间: 2026-06-01T00:00:00Z", message)

    def test_format_status_uses_quality_and_dynamic_source_count_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            (project / "AGENTS.md").write_text("rules", encoding="utf-8")
            (project / "package.json").write_text('{"scripts":{"test":"pytest"}}', encoding="utf-8")
            wiki = FakeWiki(
                [
                    {
                        "id": "profile_1",
                        "kind": "project_profile",
                        "name": "order",
                        "local_paths": [str(project)],
                        "status": "verified",
                        "documentation_index": ["docs/project-map.md", "docs/component-contract.md"],
                    },
                    {"id": "source_1", "kind": "external_source_index", "project": "order"},
                    {"id": "source_2", "kind": "external_source_index", "project": "order"},
                ]
            )
            catalog = ProjectProfileCatalog(wiki=wiki, registry_projects=lambda: [])
            profile = catalog.find("order")

            message = catalog.format_status(profile)

            self.assertIn("当前项目：order", message)
            self.assertIn("初始化质量：complete", message)
            self.assertIn("质量门缺口：无", message)
            self.assertIn("动态来源索引：2 条", message)


if __name__ == "__main__":
    unittest.main()
