import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.services.task_service import TaskService


class RecordingSourceIndexer:
    def __init__(self, context=None):
        self.context = context
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return self.context


class RecordingKanban:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "kanban_task_id": "kanban_1"}


def _make_service(tmp: str, *, source_context=None):
    root = Path(tmp)
    ledger = TaskLedger(root / "ledger.db")
    resolver = ProjectResolver(
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
    )
    wiki = LocalLlmWikiAdapter(root / "wiki")
    source_indexer = RecordingSourceIndexer(source_context)
    kanban = RecordingKanban()
    service = TaskService(
        ledger=ledger,
        resolver=resolver,
        wiki=wiki,
        source_indexer=source_indexer,
        kanban_create=kanban,
    )
    return service, ledger, source_indexer, kanban


class TaskServiceTest(unittest.TestCase):
    def test_tool_task_create_requires_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ledger, _source_indexer, _kanban = _make_service(tmp)

            result = service.tool_task_create({"requirement": "   "})

            self.assertEqual(result, {"ok": False, "error": "requirement is required"})

    def test_tool_task_create_normalizes_project_runner_and_session_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, ledger, _source_indexer, _kanban = _make_service(tmp)

            result = service.tool_task_create(
                {
                    "requirement": "订单列表新增店铺筛选",
                    "project": "bps-admin",
                    "runner": "codex_cli",
                    "task_kind": "bugfix",
                    "root_task_id": "task_root",
                    "parent_task_id": "task_parent",
                    "source_branch": "feature/root",
                    "branch_policy": "inherit_root_branch",
                    "action": "bugfix",
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "planned")
            task = ledger.get_task(result["task_id"])
            self.assertEqual(task["project_path"], "/repo/bps-admin")
            self.assertEqual(task["task_kind"], "bugfix")
            self.assertEqual(task["root_task_id"], "task_root")
            self.assertEqual(task["parent_task_id"], "task_parent")
            session = task["task_session"]
            self.assertEqual(session["runner"]["provider"], "codex_cli")
            self.assertEqual(session["source_branch"], "feature/root")
            self.assertEqual(session["branch_policy"], "inherit_root_branch")
            self.assertEqual(session["action"], "bugfix")

    def test_tool_task_create_delegates_source_url_indexing(self):
        source_context = {
            "read_status": "success",
            "source_type": "feishu_wiki",
            "url": "https://bestfulfill.feishu.cn/wiki/Token123",
            "title": "来源标题",
            "summary_markdown": "来源摘要",
        }
        with tempfile.TemporaryDirectory() as tmp:
            service, ledger, source_indexer, _kanban = _make_service(tmp, source_context=source_context)

            result = service.tool_task_create(
                {
                    "requirement": "订单列表新增店铺筛选",
                    "project": "bps-admin",
                    "source_url": "https://bestfulfill.feishu.cn/wiki/Token123",
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(source_indexer.calls, ["https://bestfulfill.feishu.cn/wiki/Token123"])
            task = ledger.get_task(result["task_id"])
            stored_context = task["source"]["source_context"]
            self.assertEqual(stored_context["read_status"], "success")
            self.assertEqual(stored_context["url"], "https://bestfulfill.feishu.cn/wiki/Token123")
            self.assertIn("来源标题", result["message"])

    def test_tool_task_status_returns_compatible_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ledger, _source_indexer, _kanban = _make_service(tmp)
            created = service.tool_task_create({"requirement": "订单列表新增店铺筛选", "project": "bps-admin"})

            result = service.tool_task_status({"task_id": created["task_id"]})

            self.assertTrue(result["ok"])
            self.assertEqual(result["task_id"], created["task_id"])
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["project_path"], "/repo/bps-admin")
            self.assertEqual(result["next_actions"], ["coding_task_run"])

    def test_task_status_payload_reads_source_fields_from_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, ledger, _source_indexer, _kanban = _make_service(tmp)
            ledger.create_task(
                task_id="task_projection",
                source={
                    "type": "legacy_type",
                    "project_name": "bps-admin",
                    "source_context": {
                        "read_status": "failed",
                        "source_type": "legacy_source",
                        "url": "https://legacy.example/doc",
                        "error": "missing scope",
                        "recovery_action": "legacy recovery",
                    },
                },
                requirement_summary="订单列表新增店铺筛选",
                project_path="/repo/bps-admin",
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            projection = SimpleNamespace(
                status="permission_missing",
                source_type="projected_source",
                url="https://projected.example/doc",
                recovery_action="projected recovery",
                codex_resolvable=True,
                resolution_owner="codex",
            )

            with patch(
                "coding_orchestration.services.task_utils.source_projection_from_source",
                return_value=projection,
                create=True,
            ):
                payload = service.task_status_payload("task_projection")

            self.assertEqual(payload["source_status"], "permission_missing")
            self.assertEqual(payload["source_type"], "projected_source")
            self.assertEqual(payload["source_url"], "https://projected.example/doc")
            self.assertEqual(payload["source_recovery_action"], "projected recovery")
            self.assertEqual(payload["next_actions"], ["coding_task_run", "coding_task_status"])

    def test_task_status_payload_keeps_source_without_context_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, ledger, _source_indexer, _kanban = _make_service(tmp)
            ledger.create_task(
                task_id="task_manual",
                source={
                    "type": "manual",
                    "project_name": "bps-admin",
                },
                requirement_summary="订单列表新增店铺筛选",
                project_path="/repo/bps-admin",
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
            )

            payload = service.task_status_payload("task_manual")

            self.assertEqual(payload["source_status"], "missing")
            self.assertEqual(payload["source_type"], "manual")
            self.assertEqual(payload["next_actions"], ["coding_task_run"])

    def test_next_actions_for_task_payload_uses_projection_readability(self):
        task = {"status": "planned"}
        self.assertEqual(
            TaskService.next_actions_for_task_payload(
                task,
                {
                    "source_context": {
                        "read_status": "indexed",
                        "source_type": "feishu_docx",
                        "url": "https://example.feishu.cn/docx/Token",
                        "deferred_source_resolution": True,
                        "codex_resolvable": True,
                    }
                },
            ),
            ["coding_task_run", "coding_task_status"],
        )
        self.assertEqual(
            TaskService.next_actions_for_task_payload(
                task,
                {
                    "source_context": {
                        "read_status": "failed",
                        "source_type": "feishu_docx",
                        "url": "https://example.feishu.cn/docx/Token",
                        "error": "missing scope: docx:document:readonly",
                    }
                },
            ),
            ["coding_lark_preflight", "coding_source_resolve", "coding_task_status"],
        )


if __name__ == "__main__":
    unittest.main()
