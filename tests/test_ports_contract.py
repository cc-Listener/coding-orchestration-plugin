import unittest

from coding_orchestration.ports import KnowledgePort, LedgerPort, RunnerPort, SourcePort, SourceResult, WorkItemPort


class PortsContractTest(unittest.TestCase):
    def test_ports_are_runtime_checkable_protocols(self):
        self.assertTrue(getattr(WorkItemPort, "_is_protocol", False))
        self.assertTrue(getattr(RunnerPort, "_is_protocol", False))
        self.assertTrue(getattr(LedgerPort, "_is_protocol", False))
        self.assertTrue(getattr(KnowledgePort, "_is_protocol", False))
        self.assertTrue(getattr(SourcePort, "_is_protocol", False))

    def test_source_result_normalizes_reader_context_without_exposing_reader_shape(self):
        result = SourceResult.from_context(
            {
                "read_status": "success",
                "source_type": "feishu_project_story",
                "url": "https://project.feishu.cn/foo/story/detail/123",
                "title": "订单状态优化",
                "summary_markdown": "需求正文",
                "raw_fields": [{"name": "验收标准", "value": "状态准确"}],
            }
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source_type, "feishu_project_story")
        self.assertEqual(result.url, "https://project.feishu.cn/foo/story/detail/123")
        self.assertEqual(result.title, "订单状态优化")
        self.assertEqual(result.context["raw_fields"][0]["name"], "验收标准")

    def test_source_result_maps_failed_context_to_stable_status(self):
        result = SourceResult.from_context(
            {
                "read_status": "failed",
                "source_type": "feishu_docx",
                "url": "https://example.feishu.cn/docx/DocxToken",
                "error": "need_user_authorization, current command requires scope(s): docx:document:readonly",
                "recovery_action": "rtk lark-cli auth login",
            }
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "auth_needed")
        self.assertEqual(result.error, "need_user_authorization, current command requires scope(s): docx:document:readonly")
        self.assertEqual(result.recovery_action, "rtk lark-cli auth login")
