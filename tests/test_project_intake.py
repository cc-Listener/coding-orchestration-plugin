import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_intake import ProjectIntakeRule
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


READY_RULE = {
    "name": "待接入需求",
    "space": "BPS空间",
    "workitem_type": "story",
    "query": '状态 = "待接入"',
}


class FakeProjectMcpAdapter:
    def __init__(self, results=None):
        self.config = type("Config", (), {"transport": "stdio", "domain": "https://project.feishu.cn"})()
        self.allowed_tools = {"search_by_mql"}
        self.results = results or {}
        self.calls = []

    def is_enabled(self):
        return True

    def call_tool(self, tool, arguments):
        self.calls.append((tool, arguments))
        return {"ok": True, "status": "ok", "tool": tool, "result": self.results.get(tool, {})}


def make_orchestrator(tmp: str, *, project_mcp_adapter=None) -> CodingOrchestrator:
    root = Path(tmp)
    return CodingOrchestrator(
        ledger=TaskLedger(root / "ledger.db"),
        resolver=ProjectResolver(
            ProjectRegistry([{"name": "bps-admin", "path": "/repo/bps-admin", "keywords": ["订单"]}])
        ),
        wiki=LocalLlmWikiAdapter(root / "wiki"),
        project_mcp_adapter=project_mcp_adapter,
    )


class ProjectIntakeTest(unittest.TestCase):
    def test_rule_builds_search_args_from_status_condition(self):
        rule = ProjectIntakeRule(
            name="待接入需求",
            space="BPS空间",
            workitem_type="需求",
            mql='状态 = "待接入"',
            create_coding_task=True,
        )

        self.assertEqual(rule.search_args()["space"], "BPS空间")
        self.assertEqual(rule.search_args()["workitem_type"], "需求")
        self.assertIn("待接入", rule.search_args()["query"])

    def test_intake_sync_reuses_existing_task_binding_for_same_story(self):
        adapter = FakeProjectMcpAdapter(
            results={
                "search_by_mql": {
                    "items": [
                        {
                            "id": "123",
                            "workitem_type": "story",
                            "space_key": "z9b9t3",
                            "title": "订单列表新增筛选",
                            "url": "https://project.feishu.cn/z9b9t3/story/detail/123",
                        }
                    ]
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(tmp, project_mcp_adapter=adapter)

            first = orchestrator.tool_project_intake_sync({"rule": READY_RULE, "dry_run": False})
            second = orchestrator.tool_project_intake_sync({"rule": READY_RULE, "dry_run": False})

            self.assertEqual(first["created_tasks"], 1)
            self.assertEqual(second["created_tasks"], 0)
            self.assertEqual(second["existing_tasks"], 1)

    def test_intake_sync_creates_coding_task_for_unseen_workitem(self):
        adapter = FakeProjectMcpAdapter(
            results={
                "search_by_mql": {
                    "items": [
                        {
                            "id": "story_1",
                            "title": "订单列表新增筛选",
                            "url": "https://project.feishu.cn/z9b9t3/story/detail/1",
                        }
                    ]
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(tmp, project_mcp_adapter=adapter)

            result = orchestrator.tool_project_intake_sync(
                {
                    "rule": {
                        "name": "ready",
                        "space": "BPS空间",
                        "workitem_type": "需求",
                        "mql": '状态 = "待开发"',
                    },
                    "dry_run": False,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["created_tasks"], 1)


if __name__ == "__main__":
    unittest.main()
