import tempfile
import unittest
import json
from pathlib import Path

from coding_orchestration.kanban_bridge import KanbanBridge
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class FakeDispatchTool:
    def __init__(self, result=None):
        self.result = result or {"task_id": "t_123"}
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        return self.result


class ExplodingDispatchTool:
    def __call__(self, name, args):
        raise RuntimeError("kanban offline")


def _write_workflow(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "WORKFLOW.md").write_text(
        """
# WORKFLOW

## Allowed Paths
- src/

## Test Commands
- rtk python3 -m unittest
""",
        encoding="utf-8",
    )


class KanbanBridgeTest(unittest.TestCase):
    def test_kanban_bridge_creates_task_with_idempotency_key(self):
        dispatch_tool = FakeDispatchTool()
        bridge = KanbanBridge(dispatch_tool=dispatch_tool)

        result = bridge.create_task(
            local_task_id="task_abc",
            title="订单列表新增店铺筛选",
            body="需求内容",
            assignee="coder",
            metadata={"project": "bps-admin"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["kanban_task_id"], "t_123")
        self.assertEqual(dispatch_tool.calls[0]["name"], "kanban_create")
        self.assertEqual(dispatch_tool.calls[0]["args"]["idempotency_key"], "coding:task_abc")
        self.assertEqual(dispatch_tool.calls[0]["args"]["metadata"]["local_task_id"], "task_abc")

    def test_orchestrator_task_creation_syncs_kanban_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            _write_workflow(project)
            dispatch_tool = FakeDispatchTool()
            orchestrator = CodingOrchestrator(
                ledger=TaskLedger(root / "ledger.db"),
                resolver=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "bps-admin",
                                "path": str(project),
                                "keywords": ["订单列表"],
                            }
                        ]
                    )
                ),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )
            orchestrator.set_dispatch_tool(dispatch_tool)

            created = orchestrator._create_task_from_text("--project bps-admin 订单列表新增店铺筛选")

            task = orchestrator.ledger.get_task(created.task_id)
            self.assertEqual(task["task_session"]["kanban_task_id"], "t_123")
            self.assertEqual(dispatch_tool.calls[0]["name"], "kanban_create")
            self.assertEqual(dispatch_tool.calls[0]["args"]["metadata"]["local_task_id"], created.task_id)

    def test_sync_task_status_projects_to_real_kanban_tools(self):
        cases = [
            (TaskStatus.DONE, "kanban_complete"),
            (TaskStatus.BLOCKED, "kanban_block"),
            (TaskStatus.QUEUED, "kanban_heartbeat"),
            (TaskStatus.RUNNING, "kanban_heartbeat"),
            (TaskStatus.PLANNED, "kanban_comment"),
            (TaskStatus.READY_FOR_MERGE_TEST, "kanban_comment"),
            (TaskStatus.RUNNER_FAILED, "kanban_comment"),
        ]
        for status, expected_tool in cases:
            with self.subTest(status=status.value):
                dispatch_tool = FakeDispatchTool(result={"ok": True})
                bridge = KanbanBridge(dispatch_tool=dispatch_tool)

                result = bridge.sync_task_status(
                    local_task_id="task_abc",
                    kanban_task_id="kb_123",
                    task_status=status,
                    reason="state transition",
                )

                self.assertTrue(result["ok"])
                self.assertEqual(result["tool"], expected_tool)
                self.assertEqual(dispatch_tool.calls[0]["name"], expected_tool)
                payload = dispatch_tool.calls[0]["args"]
                self.assertEqual(payload["task_id"], "kb_123")
                self.assertEqual(payload["metadata"]["local_task_id"], "task_abc")
                self.assertEqual(payload["metadata"]["task_status"], status.value)
                self.assertEqual(payload["metadata"]["task_status_display"], f"{result['task_status_label_zh']}({status.value})")

    def test_sync_task_status_failure_is_non_blocking_result(self):
        bridge = KanbanBridge(dispatch_tool=ExplodingDispatchTool())

        result = bridge.sync_task_status(
            local_task_id="task_abc",
            kanban_task_id="kb_123",
            task_status=TaskStatus.RUNNING,
            reason="state transition",
        )

        self.assertFalse(result["ok"])
        self.assertIn("kanban_sync_failed", result["reason"])

    def test_sync_task_status_treats_error_payload_as_failure(self):
        bridge = KanbanBridge(dispatch_tool=FakeDispatchTool(result={"error": "permission denied"}))

        result = bridge.sync_task_status(
            local_task_id="task_abc",
            kanban_task_id="kb_123",
            task_status=TaskStatus.DONE,
            reason="state transition",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["tool"], "kanban_complete")
        self.assertIn("permission denied", result["reason"])

    def test_sync_task_status_treats_json_ok_false_payload_as_failure(self):
        bridge = KanbanBridge(
            dispatch_tool=FakeDispatchTool(result=json.dumps({"ok": False, "reason": "not running"}))
        )

        result = bridge.sync_task_status(
            local_task_id="task_abc",
            kanban_task_id="kb_123",
            task_status=TaskStatus.RUNNING,
            reason="state transition",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["tool"], "kanban_heartbeat")
        self.assertIn("not running", result["reason"])


if __name__ == "__main__":
    unittest.main()
