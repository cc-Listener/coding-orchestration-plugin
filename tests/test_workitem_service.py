import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.project_workitem_binding import ProjectWorkitemIdentity
from coding_orchestration.services.workitem_service import WorkItemService


class FakeProjectMcpAdapter:
    def __init__(self, *, enabled=True, result=None, results=None):
        self.config = type(
            "Config",
            (),
            {
                "transport": "stdio",
                "domain": "https://project.feishu.cn",
                "token": "fake_value_for_unit_test",
            },
        )()
        self.allowed_tools = {
            "search_project_info",
            "search_by_mql",
            "create_workitem",
            "get_transition_required",
            "get_transitable_states",
            "transition_state",
        }
        self.enabled = enabled
        self.result = result or {"ok": True, "status": "ok", "tool": "unknown", "result": {"content": []}}
        self.results = results or {}
        self.calls = []

    def is_enabled(self):
        return self.enabled

    def call_tool(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool in self.results:
            result = self.results[tool]
            if isinstance(result, dict) and "ok" in result:
                return result
            return {"ok": True, "status": "ok", "tool": tool, "result": result}
        return self.result


class WorkItemServiceTest(unittest.TestCase):
    def test_search_calls_mcp_read_only_adapter(self):
        adapter = FakeProjectMcpAdapter()
        service = WorkItemService(project_mcp_adapter=adapter)

        result = service.search_workitems(
            {
                "space": "测试空间",
                "workitem_type": "需求",
                "query": "状态 = 待处理",
                "limit": 10,
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            adapter.calls,
            [
                (
                    "search_by_mql",
                    {
                        "space": "测试空间",
                        "workitem_type": "需求",
                        "query": "状态 = 待处理",
                        "limit": 10,
                    },
                )
            ],
        )

    def test_create_requires_explicit_write_confirmation(self):
        service = WorkItemService(project_mcp_adapter=FakeProjectMcpAdapter())

        result = service.create_workitem(
            {
                "space": "测试空间",
                "workitem_type": "需求",
                "title": "新增自动化需求",
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["action"], "create_workitem")

    def test_transition_checks_required_fields_before_write(self):
        adapter = FakeProjectMcpAdapter(results={"get_transition_required": {"missing": ["处理人"]}})
        service = WorkItemService(project_mcp_adapter=adapter)

        result = service.transition_state(
            {
                "workitem_url": "https://project.feishu.cn/z9b9t3/issue/detail/1",
                "target_state": "处理中",
                "confirm_write": True,
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "required_fields_missing")
        self.assertEqual(adapter.calls, [("get_transition_required", {"workitem_url": result.get("workitem_url", "https://project.feishu.cn/z9b9t3/issue/detail/1"), "target_state": "处理中"})])

    def test_bugfix_task_inherits_story_branch_when_relation_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")
            story_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/story/detail/123")
            issue_identity = ProjectWorkitemIdentity.from_url(
                "https://project.feishu.cn/z9b9t3/issue/detail/1",
                title="订单列表筛选报错",
            )
            ledger.create_task(
                task_id="task_story",
                task_kind="requirement",
                requirement_summary="订单列表新增筛选",
                source={"type": "feishu_project_story", "url": story_identity.url},
                project_path="/repo/bps-admin",
                source_branch="codex/story-123",
                root_task_id="task_story",
                parent_task_id=None,
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            ledger.upsert_project_workitem_binding(
                identity=story_identity,
                hermes_task_id="task_story",
                relation_kind="source_requirement",
                root_task_id="task_story",
            )
            created_payloads = []

            def create_task(args):
                created_payloads.append(args)
                task_id = "task_bugfix"
                ledger.create_task(
                    task_id=task_id,
                    task_kind=args.get("task_kind", "bugfix"),
                    requirement_summary=args["requirement"],
                    source={"type": "feishu_project_issue", "url": args["source_url"]},
                    project_path="/repo/bps-admin",
                    status="planned",
                    llm_wiki_refs=[],
                    human_decisions=[],
                    root_task_id=args.get("root_task_id"),
                    parent_task_id=args.get("parent_task_id"),
                    source_branch=args.get("source_branch"),
                    branch_policy=args.get("branch_policy"),
                )
                return {"ok": True, "task_id": task_id}

            service = WorkItemService(
                project_mcp_adapter=FakeProjectMcpAdapter(),
                ledger=ledger,
                create_task=create_task,
            )

            result = service.create_project_bugfix_task(
                issue_identity=issue_identity,
                source_workitem_key=story_identity.key,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["branch_policy"], "inherit_root_branch")
            self.assertEqual(created_payloads[0]["root_task_id"], "task_story")
            self.assertEqual(created_payloads[0]["parent_task_id"], "task_story")
            self.assertEqual(created_payloads[0]["source_branch"], "codex/story-123")


if __name__ == "__main__":
    unittest.main()
