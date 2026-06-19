from __future__ import annotations

import unittest

from coding_orchestration.ports import SourceResult
from coding_orchestration.source_projection import (
    source_projection_from_context,
    source_projection_from_result,
    source_projection_from_source,
    source_projection_to_dict,
)


class SourceProjectionTest(unittest.TestCase):
    def test_projection_from_result_keeps_stable_fields_and_legacy_context(self):
        result = SourceResult.from_context(
            {
                "read_status": "indexed",
                "source_type": "feishu_docx",
                "url": "https://example.feishu.cn/docx/DocToken",
                "document_kind": "docx",
                "document_token": "DocToken",
                "resolution_owner": "codex",
                "codex_resolvable": True,
                "deferred_source_resolution": True,
                "lark_cli_command": "rtk lark-cli docs +fetch --doc https://example.feishu.cn/docx/DocToken",
                "recovery_action": "授权后重试",
                "private_reader_payload": {"token": "must-not-leak"},
            }
        )

        projection = source_projection_from_result(result)

        self.assertEqual(projection.status, "deferred")
        self.assertEqual(projection.source_type, "feishu_docx")
        self.assertEqual(projection.url, "https://example.feishu.cn/docx/DocToken")
        self.assertTrue(projection.codex_resolvable)
        self.assertTrue(projection.deferred_source_resolution)
        self.assertEqual(projection.resolution_owner, "codex")
        self.assertIn("lark-cli docs +fetch", projection.lark_cli_command)
        self.assertEqual(projection.legacy_context["document_token"], "DocToken")
        self.assertNotIn("private_reader_payload", projection.legacy_context)

    def test_projection_from_source_uses_top_level_fallbacks_and_summary_fields(self):
        projection = source_projection_from_source(
            {
                "type": "feishu_project_story",
                "title": "订单筛选 Story",
                "url": "https://project.feishu.cn/story/1",
                "source_context": {
                    "read_status": "success",
                    "raw_fields_summary": "后端、管理后台和移动端都要支持筛选。",
                    "raw_fields": [{"name": "验收标准", "value": "多端一致"}],
                },
            }
        )

        self.assertEqual(projection.status, "ok")
        self.assertEqual(projection.source_type, "feishu_project_story")
        self.assertEqual(projection.title, "订单筛选 Story")
        self.assertEqual(projection.url, "https://project.feishu.cn/story/1")
        self.assertEqual(projection.raw_fields_summary, "后端、管理后台和移动端都要支持筛选。")
        self.assertEqual(projection.raw_fields, [{"name": "验收标准", "value": "多端一致"}])

    def test_projection_from_empty_context_is_missing(self):
        projection = source_projection_from_context(None)

        self.assertEqual(projection.status, "missing")
        self.assertFalse(projection.ok)
        self.assertEqual(projection.legacy_context, {})

    def test_projection_to_dict_omits_legacy_context(self):
        projection = source_projection_from_context(
            {
                "read_status": "indexed",
                "source_type": "feishu_docx",
                "url": "https://example.feishu.cn/docx/DocToken",
                "deferred_source_resolution": True,
                "codex_resolvable": True,
                "private_reader_payload": {"token": "must-not-leak"},
            }
        )

        payload = source_projection_to_dict(projection)

        self.assertEqual(
            payload,
            {
                "ok": False,
                "status": "deferred",
                "source_type": "feishu_docx",
                "url": "https://example.feishu.cn/docx/DocToken",
                "codex_resolvable": True,
                "deferred_source_resolution": True,
            },
        )
        self.assertNotIn("legacy_context", payload)
        self.assertNotIn("private_reader_payload", payload)


if __name__ == "__main__":
    unittest.main()
