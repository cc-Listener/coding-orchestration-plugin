import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.ports import SourceResult
from coding_orchestration.project_workitem_binding import ProjectWorkitemIdentity
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class FakeFeishuProjectReader:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def read_from_text(self, text, gateway=None):
        self.calls.append((text, gateway))
        return self.context


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
            "create_wbs_draft",
            "edit_wbs_draft",
            "publish_wbs_draft",
            "get_transition_required",
            "get_transitable_states",
            "transition_state",
            "add_comment",
        }
        self.enabled = enabled
        self.result = result or {"ok": True, "status": "ok", "result": {"content": []}}
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


def _make_orchestrator(tmp: str, *, source_context=None, project_mcp_adapter=None) -> CodingOrchestrator:
    root = Path(tmp)
    return CodingOrchestrator(
        ledger=TaskLedger(root / "ledger.db"),
        resolver=ProjectResolver(
            ProjectRegistry(
                [
                    {
                        "name": "bps-admin",
                        "aliases": ["BPS"],
                        "path": "/repo/bps-admin",
                        "keywords": ["订单"],
                    }
                ]
            )
        ),
        wiki=LocalLlmWikiAdapter(root / "wiki"),
        feishu_project_reader=FakeFeishuProjectReader(source_context),
        project_mcp_adapter=project_mcp_adapter,
    )


class OrchestratorToolsTest(unittest.TestCase):
    def test_extracts_document_link_without_chinese_punctuation_suffix(self):
        link = CodingOrchestrator._extract_first_feishu_document_link(
            "需求来源：https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh；背景：供应商模块"
        )

        self.assertIsNotNone(link)
        self.assertEqual(link["document_kind"], "wiki")
        self.assertEqual(link["document_token"], "YNU8wYMwBiJv5AkYQIJcQ4donsh")
        self.assertEqual(link["url"], "https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh")

    def test_tool_task_create_uses_structured_args_without_gateway_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = _make_orchestrator(tmp)

            result = orchestrator.tool_task_create(
                {
                    "requirement": "订单列表新增店铺筛选",
                    "project": "bps-admin",
                    "source_url": "",
                }
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["task_id"].startswith("task_"))
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["status_label_zh"], "已规划")
            self.assertEqual(result["status_display"], "已规划(planned)")
            self.assertIn("已记录新任务", result["message"])

    def test_tool_task_status_returns_structured_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = _make_orchestrator(tmp)
            created = orchestrator.tool_task_create({"requirement": "订单列表新增店铺筛选", "project": "bps-admin"})

            result = orchestrator.tool_task_status({"task_id": created["task_id"]})

            self.assertTrue(result["ok"])
            self.assertEqual(result["task_id"], created["task_id"])
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["project_path"], "/repo/bps-admin")

    def test_tool_task_run_can_request_manual_qa_mode(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.calls = []

            def command_coding_qa(self, raw_args: str) -> str:
                self.calls.append(("qa", raw_args))
                return f"[{raw_args}] QA run 已完成：run_qa"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = RecordingOrchestrator(
                ledger=TaskLedger(root / "ledger.db"),
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
            )

            result = orchestrator.tool_task_run({"task_id": "task_qa", "mode": "qa"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "qa")
            self.assertEqual(orchestrator.calls, [("qa", "task_qa")])

    def test_tool_source_resolve_returns_structured_failure_instead_of_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = _make_orchestrator(
                tmp,
                source_context={
                    "read_status": "failed",
                    "source_type": "feishu_wiki",
                    "url": "https://bestfulfill.feishu.cn/wiki/Token123",
                    "error": "lark-cli user identity needs_refresh",
                    "deferred_source_resolution": True,
                    "requires_human_context": False,
                },
            )

            result = orchestrator.tool_source_resolve({"url": "https://bestfulfill.feishu.cn/wiki/Token123"})

            self.assertFalse(result["ok"])
            self.assertIn(result["source_status"], {"auth_needed", "deferred"})
            self.assertNotEqual(result.get("task_status"), "blocked")
            self.assertIn("needs_refresh", result["error"])

    def test_tool_source_resolve_prefers_source_result_contract(self):
        class SourceResultResolver:
            def __init__(self):
                self.calls = []

            def resolve_source_result(self, args, gateway=None):
                self.calls.append((args, gateway))
                return SourceResult.from_context(
                    {
                        "read_status": "success",
                        "source_type": "feishu_docx",
                        "url": "https://example.feishu.cn/docx/DocxToken",
                        "title": "接口文档",
                        "summary_markdown": "文档正文",
                    }
                )

            def resolve_source(self, args, gateway=None):
                raise AssertionError("tool_source_resolve should use resolve_source_result")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resolver = SourceResultResolver()
            orchestrator = CodingOrchestrator(
                ledger=TaskLedger(root / "ledger.db"),
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                source_resolver=resolver,
            )

            result = orchestrator.tool_source_resolve({"url": "https://example.feishu.cn/docx/DocxToken"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["source_status"], "ok")
            self.assertEqual(result["source_type"], "feishu_docx")
            self.assertEqual(result["title"], "接口文档")
            self.assertEqual(len(resolver.calls), 1)

    def test_tool_task_create_indexes_source_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = _make_orchestrator(
                tmp,
                source_context={
                    "read_status": "failed",
                    "source_type": "feishu_wiki",
                    "url": "https://bestfulfill.feishu.cn/wiki/Token123",
                    "error": "lark-cli user identity needs_refresh",
                    "deferred_source_resolution": True,
                    "requires_human_context": False,
                },
            )

            result = orchestrator.tool_task_create(
                {
                    "requirement": "订单列表新增店铺筛选",
                    "project": "bps-admin",
                    "source_url": "https://bestfulfill.feishu.cn/wiki/Token123",
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "needs_human")
            self.assertEqual(result["status_label_zh"], "待人工确认")
            self.assertEqual(result["status_display"], "待人工确认(needs_human)")
            self.assertNotIn("machine_status", result)
            self.assertNotEqual(result["status"], "blocked")

    def test_project_mcp_preflight_uses_adapter_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter()
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)

            result = orchestrator.tool_project_mcp_preflight({"include_tools": True})

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["transport"], "stdio")
            self.assertIn("search_by_mql", result["allowed_tools"])
            self.assertNotIn("token", str(result).lower())

    def test_project_workitem_search_calls_search_by_mql_with_read_only_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter()
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)

            result = orchestrator.tool_project_workitem_search(
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

    def test_project_workitem_create_requires_explicit_write_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=FakeProjectMcpAdapter())

            result = orchestrator.tool_project_workitem_create(
                {
                    "space": "测试空间",
                    "workitem_type": "需求",
                    "title": "新增自动化需求",
                }
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "confirmation_required")

    def test_project_workitem_create_calls_create_workitem_when_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter()
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)

            result = orchestrator.tool_project_workitem_create(
                {
                    "space": "测试空间",
                    "workitem_type": "需求",
                    "title": "新增自动化需求",
                    "fields": {"优先级": "P1"},
                    "confirm_write": True,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(adapter.calls[0][0], "create_workitem")
            self.assertEqual(adapter.calls[0][1]["fields"]["优先级"], "P1")

    def test_bugfix_intake_creates_coding_bugfix_task_and_moves_issue_to_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter(
                results={
                    "search_by_mql": {
                        "items": [
                            {
                                "id": "1",
                                "workitem_type": "issue",
                                "space_key": "z9b9t3",
                                "title": "订单列表筛选报错",
                                "url": "https://project.feishu.cn/z9b9t3/issue/detail/1",
                                "related_story_url": "https://project.feishu.cn/z9b9t3/story/detail/123",
                            }
                        ]
                    },
                    "get_transition_required": {"missing": []},
                    "get_transitable_states": {"states": ["处理中"]},
                    "transition_state": {"ok": True},
                }
            )
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)
            story_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/story/detail/123")
            orchestrator.ledger.create_task(
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
            orchestrator.ledger.upsert_project_workitem_binding(
                identity=story_identity,
                hermes_task_id="task_story",
                relation_kind="source_requirement",
                root_task_id="task_story",
            )

            result = orchestrator.tool_project_bugfix_intake(
                {
                    "space": "BPS空间",
                    "query": '状态 = "待处理"',
                    "transition_to": "处理中",
                    "confirm_write": True,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["created_tasks"], 1)
            bugfix_task = orchestrator.ledger.get_task(result["tasks"][0]["task_id"])
            self.assertEqual(bugfix_task["root_task_id"], "task_story")
            self.assertEqual(bugfix_task["parent_task_id"], "task_story")
            self.assertEqual(bugfix_task["source_branch"], "codex/story-123")
            self.assertEqual(bugfix_task["branch_policy"], "inherit_root_branch")

    def test_bugfix_intake_without_story_relation_marks_task_for_manual_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter(
                results={
                    "search_by_mql": {
                        "items": [
                            {
                                "id": "2",
                                "workitem_type": "issue",
                                "space_key": "z9b9t3",
                                "title": "导出按钮无响应",
                                "url": "https://project.feishu.cn/z9b9t3/issue/detail/2",
                            }
                        ]
                    }
                }
            )
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)

            result = orchestrator.tool_project_bugfix_intake(
                {
                    "space": "BPS空间",
                    "query": '状态 = "待处理"',
                    "dry_run": False,
                }
            )

            bugfix_task = orchestrator.ledger.get_task(result["tasks"][0]["task_id"])
            binding = orchestrator.ledger.find_project_workitem_binding(
                "feishu-project:https://project.feishu.cn:z9b9t3:issue:2"
            )
            self.assertEqual(bugfix_task["root_task_id"], bugfix_task["task_id"])
            self.assertIsNone(bugfix_task["parent_task_id"])
            self.assertEqual(bugfix_task["branch_policy"], "own_branch")
            self.assertTrue(binding["metadata"]["needs_story_link"])

    def test_successful_bugfix_completion_adds_project_comment_without_exposing_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter(results={"add_comment": {"comment_id": "comment_1"}})
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)
            issue_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/issue/detail/9")
            orchestrator.ledger.create_task(
                task_id="task_bugfix",
                task_kind="bugfix",
                requirement_summary="订单列表筛选报错",
                source={"type": "feishu_project_issue", "url": issue_identity.url},
                project_path="/repo/bps-admin",
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator.ledger.upsert_project_workitem_binding(
                identity=issue_identity,
                hermes_task_id="task_bugfix",
                relation_kind="bugfix_source",
                root_task_id="task_bugfix",
            )

            result = orchestrator._writeback_project_bugfix_completion(
                "task_bugfix",
                {
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                    "report": {
                        "summary": "已修复筛选报错",
                        "test_commands": ["rtk pnpm test"],
                        "verification_summary": "单元测试通过 MCP_USER_TOKEN=unit_test_value",
                    },
                },
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(adapter.calls[-1][0], "add_comment")
            self.assertEqual(adapter.calls[-1][1]["workitem_url"], issue_identity.url)
            self.assertNotIn("MCP_USER_TOKEN=unit_test_value", adapter.calls[-1][1]["content"])

    def test_wbs_update_creates_draft_edits_rows_and_publishes_when_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter(
                results={
                    "create_wbs_draft": {"draft_id": "draft_1"},
                    "edit_wbs_draft": {"row_uuid": "row_1"},
                    "publish_wbs_draft": {"published": True},
                }
            )
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)

            result = orchestrator.tool_project_wbs_update(
                {
                    "workitem_url": "https://project.feishu.cn/z9b9t3/story/detail/1",
                    "rows": [
                        {
                            "name": "后端接口开发",
                            "owner": "张三",
                            "schedule": "2026-06-15~2026-06-16",
                            "estimate": 2,
                            "actual_hours": 0,
                        }
                    ],
                    "publish": True,
                    "confirm_write": True,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(
                [call[0] for call in adapter.calls],
                ["create_wbs_draft", "edit_wbs_draft", "publish_wbs_draft"],
            )

    def test_state_transition_checks_required_fields_before_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FakeProjectMcpAdapter(
                results={
                    "get_transition_required": {"missing": []},
                    "get_transitable_states": {"states": ["处理中", "已修复"]},
                    "transition_state": {"url": "https://project.feishu.cn/z9b9t3/issue/detail/1"},
                }
            )
            orchestrator = _make_orchestrator(tmp, project_mcp_adapter=adapter)

            result = orchestrator.tool_project_state_transition(
                {
                    "workitem_url": "https://project.feishu.cn/z9b9t3/issue/detail/1",
                    "target_state": "处理中",
                    "confirm_write": True,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(
                [call[0] for call in adapter.calls],
                ["get_transition_required", "get_transitable_states", "transition_state"],
            )


if __name__ == "__main__":
    unittest.main()
