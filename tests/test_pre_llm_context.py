import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


def make_orchestrator(root: Path) -> CodingOrchestrator:
    return CodingOrchestrator(
        ledger=TaskLedger(root / "ledger.db"),
        resolver=ProjectResolver(ProjectRegistry([])),
        wiki=LocalLlmWikiAdapter(root / "wiki"),
        run_root=root / "runs",
        workspace_root=root / "workspaces",
    )


class PreLlmContextTest(unittest.TestCase):
    def test_pre_llm_context_injects_active_task_and_next_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = make_orchestrator(root)
            orchestrator.ledger.create_task(
                task_id="task_123",
                source={
                    "type": "feishu_wiki",
                    "project_name": "bps-admin",
                    "source_context": {
                        "source_type": "feishu_wiki",
                        "read_status": "failed",
                        "error": "lark-cli auth needs_refresh",
                        "deferred_source_resolution": True,
                    },
                },
                requirement_summary="订单列表新增店铺筛选",
                project_path=str(root / "bps-admin"),
                status=TaskStatus.SOURCE_AUTH_NEEDED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DRAFT.value,
            )
            orchestrator.ledger.bind_active_task(
                binding_key="feishu:chat:s1",
                task_id="task_123",
                scope={"platform": "feishu", "chat_id": "s1"},
            )

            result = orchestrator.pre_llm_call(
                session_id="s1",
                user_message="继续",
                conversation_history=[],
                is_first_turn=False,
                model="test",
                platform="feishu",
            )

            self.assertIsNotNone(result)
            self.assertIn("context", result)
            context = result["context"]
            self.assertIn("task_123", context)
            self.assertIn(TaskStatus.SOURCE_AUTH_NEEDED.value, context)
            self.assertIn("auth_needed", context)
            self.assertIn("coding_lark_preflight", context)
            self.assertIn("coding_task_run", context)

    def test_pre_llm_context_returns_none_without_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            result = orchestrator.pre_llm_call(
                session_id="missing",
                user_message="普通对话",
                conversation_history=[],
                is_first_turn=True,
                model="test",
                platform="feishu",
            )

            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
