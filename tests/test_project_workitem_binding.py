import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_workitem_binding import ProjectWorkitemIdentity
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class ProjectWorkitemBindingTest(unittest.TestCase):
    def _make_orchestrator(self, tmp: str) -> CodingOrchestrator:
        root = Path(tmp)
        return CodingOrchestrator(
            ledger=TaskLedger(root / "ledger.db"),
            resolver=ProjectResolver(ProjectRegistry([{"name": "bps-admin", "path": "/repo/bps-admin", "keywords": ["订单"]}])),
            wiki=LocalLlmWikiAdapter(root / "wiki"),
            project_mcp_adapter=None,
        )

    def test_ledger_upserts_project_workitem_binding_and_finds_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")
            ledger.create_task(
                task_id="task_story_1",
                source={"type": "feishu_project_story"},
                requirement_summary="订单列表新增筛选",
                project_path=None,
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                task_kind="requirement",
            )
            identity = ProjectWorkitemIdentity(
                domain="https://project.feishu.cn",
                space_key="z9b9t3",
                workitem_type="story",
                workitem_id="123",
                url="https://project.feishu.cn/z9b9t3/story/detail/123",
                title="订单列表新增筛选",
            )

            ledger.upsert_project_workitem_binding(
                identity=identity,
                hermes_task_id="task_story_1",
                relation_kind="source_requirement",
                root_task_id="task_story_1",
            )

            found = ledger.find_task_by_project_workitem(identity.key)
            self.assertEqual(found["task_id"], "task_story_1")
            bindings = ledger.list_project_workitem_bindings("task_story_1")
            self.assertEqual(bindings[0]["project_workitem_key"], identity.key)
            self.assertEqual(bindings[0]["relation_kind"], "source_requirement")

    def test_project_workitem_identity_parses_story_url(self):
        identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/story/detail/123")

        self.assertEqual(identity.space_key, "z9b9t3")
        self.assertEqual(identity.workitem_type, "story")
        self.assertEqual(identity.workitem_id, "123")
        self.assertEqual(identity.key, "feishu-project:https://project.feishu.cn:z9b9t3:story:123")

    def test_bugfix_task_links_issue_to_requirement_root_when_relation_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(tmp)
            story_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/story/detail/123")
            issue_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/issue/detail/456")
            orchestrator.ledger.create_task(
                task_id="task_story",
                task_kind="requirement",
                requirement_summary="订单列表新增筛选",
                source={"type": "feishu_project_story", "url": story_identity.url},
                project_path="/repo/bps-admin",
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                root_task_id="task_story",
                parent_task_id=None,
                task_session={"source_branch": "codex/story-123"},
            )
            orchestrator.ledger.upsert_project_workitem_binding(
                identity=story_identity,
                hermes_task_id="task_story",
                relation_kind="source_requirement",
                root_task_id="task_story",
            )

            result = orchestrator._create_project_bugfix_task(
                issue_identity=issue_identity,
                source_workitem_key=story_identity.key,
            )

            task = orchestrator.ledger.get_task(result["task_id"])
            self.assertEqual(task["root_task_id"], "task_story")
            self.assertEqual(task["parent_task_id"], "task_story")
            self.assertEqual(task["source_branch"], "codex/story-123")
            self.assertEqual(task["branch_policy"], "inherit_root_branch")
            binding = orchestrator.ledger.find_project_workitem_binding(issue_identity.key)
            self.assertEqual(binding["relation_kind"], "bugfix_source")
            self.assertEqual(binding["source_workitem_key"], story_identity.key)
            self.assertEqual(binding["root_task_id"], "task_story")
            self.assertEqual(binding["parent_task_id"], "task_story")
            self.assertFalse(binding["metadata"]["needs_story_link"])

    def test_bugfix_without_story_link_creates_independent_root_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = self._make_orchestrator(tmp)
            issue_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/issue/detail/456")

            result = orchestrator._create_project_bugfix_task(
                issue_identity=issue_identity,
                source_workitem_key=None,
            )

            task = orchestrator.ledger.get_task(result["task_id"])
            binding = orchestrator.ledger.find_project_workitem_binding(issue_identity.key)
            self.assertEqual(task["root_task_id"], task["task_id"])
            self.assertIsNone(task["parent_task_id"])
            self.assertEqual(task["branch_policy"], "own_branch")
            self.assertEqual(binding["root_task_id"], task["task_id"])
            self.assertTrue(binding["metadata"]["needs_story_link"])


if __name__ == "__main__":
    unittest.main()
