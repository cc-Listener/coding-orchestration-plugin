import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from coding_orchestration.feishu_project_reader import FeishuProjectReader


class FeishuProjectReaderTest(unittest.TestCase):
    def test_extracts_story_detail_link(self):
        link = FeishuProjectReader.extract_first_link(
            "https://project.feishu.cn/z9b9t3/story/detail/6983769492"
        )

        self.assertIsNotNone(link)
        self.assertEqual(link.project_key, "z9b9t3")
        self.assertEqual(link.work_item_type_key, "story")
        self.assertEqual(link.work_item_id, "6983769492")

    def test_extracts_wiki_document_link(self):
        link = FeishuProjectReader.extract_first_document_link(
            "接口文档：https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
        )

        self.assertIsNotNone(link)
        self.assertEqual(link.document_kind, "wiki")
        self.assertEqual(link.document_token, "FLArwwLCaikbg6kVhWRcxpFQnTe")
        self.assertEqual(link.url, "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe")

    def test_normalizes_work_item_payload_to_codex_context(self):
        reader = FeishuProjectReader()
        link = FeishuProjectReader.extract_first_link(
            "https://project.feishu.cn/z9b9t3/story/detail/6983769492"
        )

        context = reader.normalize_payload(
            link,
            {
                "data": {
                    "name": "BPS 订单列表新增店铺筛选",
                    "field_value_pairs": [
                        {"field_name": "需求描述", "value": "订单列表需要支持按店铺筛选。"},
                        {"field_name": "状态", "value": "待开发"},
                    ],
                }
            },
        )

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["source_type"], "feishu_project_story")
        self.assertIn("BPS 订单列表新增店铺筛选", context["summary_markdown"])
        self.assertIn("订单列表需要支持按店铺筛选", context["summary_markdown"])
        self.assertIn("状态", context["summary_markdown"])

    def test_normalizes_lark_doc_payload_to_codex_context(self):
        reader = FeishuProjectReader()
        link = FeishuProjectReader.extract_first_document_link(
            "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
        )

        context = reader._coerce_document_context(
            link,
            {
                "ok": True,
                "data": {
                    "document": {
                        "document_id": "Amt4d85oXoHvVTxqkiqcmmLTnBe",
                        "revision_id": 212,
                        "content": "## 店铺列表查询接口\n\n## 更新店铺接口(新增)",
                    }
                },
            },
        )

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["source_type"], "feishu_wiki")
        self.assertEqual(context["document_id"], "Amt4d85oXoHvVTxqkiqcmmLTnBe")
        self.assertIn("更新店铺接口", context["summary_markdown"])

    def test_lark_cli_document_failure_requires_human_context(self):
        reader = FeishuProjectReader()

        with patch("coding_orchestration.feishu_project_reader.subprocess.run") as run:
            run.return_value = CompletedProcess(
                args=["lark-cli"],
                returncode=3,
                stdout='{"ok": false, "error": {"type": "hermes", "message": "hermes context detected but lark-cli is not bound to it"}}',
                stderr="",
            )

            context = reader.read_from_text(
                "接口文档：https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
            )

        self.assertEqual(context["read_status"], "failed")
        self.assertEqual(context["source_type"], "feishu_wiki")
        self.assertTrue(context["requires_human_context"])
        self.assertIn("not bound", context["error"])


if __name__ == "__main__":
    unittest.main()
