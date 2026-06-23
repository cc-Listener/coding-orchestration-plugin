from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.project.project_workitem_binding import ProjectWorkitemIdentity
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner


class BugfixWritebackFlowTest(unittest.TestCase):
    def test_successful_bugfix_completion_adds_project_comment_without_exposing_secrets(self):
        class FakeProjectMcpAdapter:
            def __init__(self):
                self.calls = []

            def call_tool(self, tool, arguments):
                self.calls.append((tool, arguments))
                return {"ok": True, "status": "ok", "tool": tool, "result": {"url": arguments.get("workitem_url")}}

            def is_enabled(self):
                return True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            adapter = FakeProjectMcpAdapter()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                project_mcp_adapter=adapter,
            )
            issue_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/issue/detail/1")
            ledger.create_task(
                task_id="task_bugfix",
                source={"type": "feishu_project_issue", "url": issue_identity.url},
                requirement_summary="订单列表筛选报错",
                project_path="/repo/bps-admin",
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_kind="bugfix",
            )
            ledger.upsert_project_workitem_binding(
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
                    "run_id": "run_1",
                    "report": {
                        "summary": "已修复订单列表筛选报错。",
                        "verification_summary": "单元测试通过",
                    },
                },
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(adapter.calls[-1][0], "add_comment")
            self.assertEqual(adapter.calls[-1][1]["workitem_url"], issue_identity.url)
            self.assertIn("已修复订单列表筛选报错", adapter.calls[-1][1]["content"])
            self.assertNotIn("MCP_USER_TOKEN", str(adapter.calls[-1][1]))
