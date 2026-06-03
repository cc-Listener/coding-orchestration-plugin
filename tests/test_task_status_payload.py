import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class TaskStatusPayloadTest(unittest.TestCase):
    def test_task_status_payload_includes_source_runtime_kanban_and_next_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_123",
                source={
                    "type": "feishu_docx",
                    "project_name": "bps-admin",
                    "source_context": {
                        "read_status": "failed",
                        "source_type": "feishu_docx",
                        "url": "https://bestfulfill.feishu.cn/docx/Token123",
                        "error": "needs_refresh",
                        "recovery_action": "run lark-cli auth refresh",
                    },
                },
                requirement_summary="订单列表新增店铺筛选",
                project_path=str(root / "bps-admin"),
                status=TaskStatus.SOURCE_AUTH_NEEDED.value,
                phase=TaskPhase.DRAFT.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "project_name": "bps-admin",
                    "kanban_task_id": "kb_123",
                    "kanban_sync": {
                        "status": "ok",
                        "task_status": TaskStatus.SOURCE_AUTH_NEEDED.value,
                        "task_status_display": "来源授权待刷新(source_auth_needed)",
                    },
                    "runner": {"provider": "codex_cli"},
                },
            )
            ledger.append_agent_run("task_123", {"run_id": "run_1", "status": "running"})
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )

            payload = orchestrator._task_status_payload("task_123")

            self.assertEqual(payload["task_id"], "task_123")
            self.assertEqual(payload["status"], TaskStatus.SOURCE_AUTH_NEEDED.value)
            self.assertIn("status_label", payload)
            self.assertEqual(payload["status_label_zh"], "来源授权待刷新")
            self.assertEqual(payload["status_display"], "来源授权待刷新(source_auth_needed)")
            self.assertEqual(payload["source_status"], "auth_needed")
            self.assertEqual(payload["source_url"], "https://bestfulfill.feishu.cn/docx/Token123")
            self.assertEqual(payload["runtime_status"], "running")
            self.assertEqual(payload["last_run_id"], "run_1")
            self.assertEqual(payload["kanban_task_id"], "kb_123")
            self.assertEqual(payload["kanban_sync"]["status"], "ok")
            self.assertEqual(payload["source_recovery_action"], "run lark-cli auth refresh")
            self.assertIn("coding_lark_preflight", payload["next_actions"])

            message = orchestrator.command_coding_status("task_123")

            self.assertIn("状态：来源授权待刷新(source_auth_needed)", message)
            self.assertIn("执行阶段：draft", message)
            self.assertIn("最近运行：running", message)
            self.assertIn("Kanban 同步：成功", message)
            self.assertNotIn("Ledger 状态", message)
            self.assertNotIn("Kanban 状态", message)


if __name__ == "__main__":
    unittest.main()
