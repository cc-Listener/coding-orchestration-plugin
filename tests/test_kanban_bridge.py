import tempfile
import unittest
from pathlib import Path

from coding_orchestration.kanban_bridge import KanbanBridge
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class FakeDispatchTool:
    def __init__(self, result=None):
        self.result = result or {"task_id": "t_123"}
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        return self.result


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


if __name__ == "__main__":
    unittest.main()
