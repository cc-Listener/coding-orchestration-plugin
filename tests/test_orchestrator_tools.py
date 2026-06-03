import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class FakeFeishuProjectReader:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def read_from_text(self, text, gateway=None):
        self.calls.append((text, gateway))
        return self.context


def _make_orchestrator(tmp: str, *, source_context=None) -> CodingOrchestrator:
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
            self.assertIn("已创建编码任务", result["message"])

    def test_tool_task_status_returns_structured_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = _make_orchestrator(tmp)
            created = orchestrator.tool_task_create({"requirement": "订单列表新增店铺筛选", "project": "bps-admin"})

            result = orchestrator.tool_task_status({"task_id": created["task_id"]})

            self.assertTrue(result["ok"])
            self.assertEqual(result["task_id"], created["task_id"])
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["project_path"], "/repo/bps-admin")

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
            self.assertEqual(result["status"], "source_deferred")
            self.assertNotEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
