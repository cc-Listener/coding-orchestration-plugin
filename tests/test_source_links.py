import unittest

from coding_orchestration.source_links import (
    extract_feishu_document_link,
    extract_feishu_project_link,
    extract_meegle_link,
)


class SourceLinksTest(unittest.TestCase):
    def test_extracts_feishu_project_work_item_link_without_reader_dependencies(self):
        link = extract_feishu_project_link(
            "需求：https://project.feishu.cn/z9b9t3/story/detail/6983769492"
        )

        self.assertEqual(link.url, "https://project.feishu.cn/z9b9t3/story/detail/6983769492")
        self.assertEqual(link.project_key, "z9b9t3")
        self.assertEqual(link.work_item_type_key, "story")
        self.assertEqual(link.work_item_id, "6983769492")

    def test_extracts_feishu_document_links_without_chinese_punctuation_suffix(self):
        link = extract_feishu_document_link(
            "需求来源：https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh；背景：供应商模块"
        )

        self.assertEqual(link.url, "https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh")
        self.assertEqual(link.document_kind, "wiki")
        self.assertEqual(link.document_token, "YNU8wYMwBiJv5AkYQIJcQ4donsh")

    def test_extracts_docx_document_link(self):
        link = extract_feishu_document_link(
            "设计稿 https://example.feishu.cn/docx/Amt4d85oXoHvVTxqkiqcmmLTnBe?from=from_copylink"
        )

        self.assertEqual(link.document_kind, "docx")
        self.assertEqual(link.document_token, "Amt4d85oXoHvVTxqkiqcmmLTnBe")
        self.assertIn("?from=from_copylink", link.url)

    def test_extracts_meegle_link_as_project_work_item_identity(self):
        link = extract_meegle_link(
            "https://project.feishu.cn/z9b9t3/issue/detail/ISSUE-123"
        )

        self.assertEqual(link.project_key, "z9b9t3")
        self.assertEqual(link.work_item_type_key, "issue")
        self.assertEqual(link.work_item_id, "ISSUE-123")


if __name__ == "__main__":
    unittest.main()
