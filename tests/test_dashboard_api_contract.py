import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class DashboardApiContractTest(unittest.TestCase):
    def test_dashboard_manifest_declares_backend_api(self):
        manifest = json.loads(Path("coding_orchestration/dashboard/manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["api"], "plugin_api.py")
        self.assertEqual(manifest["tab"]["path"], "/coding")

    def test_dashboard_api_exports_router(self):
        module = importlib.import_module("coding_orchestration.dashboard.plugin_api")

        self.assertTrue(hasattr(module, "router"))

    def test_dashboard_status_payload_is_read_only_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={
                    "type": "feishu_docx",
                    "source_context": {
                        "read_status": "failed",
                        "source_type": "feishu_docx",
                        "error": "needs_refresh",
                    },
                },
                requirement_summary="订单列表新增店铺筛选",
                project_path=str(root / "repo"),
                status=TaskStatus.NEEDS_HUMAN.value,
                phase=TaskPhase.DRAFT.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )

            payload = orchestrator.dashboard_status_payload()

            self.assertEqual(payload["task_counts_by_status"][TaskStatus.NEEDS_HUMAN.value], 1)
            self.assertEqual(payload["source_health"]["auth_needed"], 1)
            self.assertIn("lark_preflight", payload)
            self.assertIn("kanban_available", payload)

    def test_dashboard_source_health_uses_source_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            source = {
                "type": "legacy_type",
                "source_context": {
                    "read_status": "failed",
                    "source_type": "legacy_source",
                    "error": "needs_refresh",
                },
            }
            ledger.create_task(
                task_id="task_projection",
                source=source,
                requirement_summary="订单列表新增店铺筛选",
                project_path=str(root / "repo"),
                status=TaskStatus.NEEDS_HUMAN.value,
                phase=TaskPhase.DRAFT.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )

            with patch(
                "coding_orchestration.orchestrator.source_projection.source_projection_from_source",
                return_value=SimpleNamespace(status="projected_deferred"),
            ) as projection:
                payload = orchestrator.dashboard_status_payload()

            projection.assert_called_once_with(source)
            self.assertEqual(payload["source_health"], {"projected_deferred": 1})


if __name__ == "__main__":
    unittest.main()
