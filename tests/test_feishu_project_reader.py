import unittest

from coding_orchestration.feishu.feishu_project_reader import FeishuProjectReader


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

    def test_extracts_wiki_document_link_without_chinese_punctuation_suffix(self):
        link = FeishuProjectReader.extract_first_document_link(
            "需求来源：https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh；背景：供应商模块"
        )

        self.assertIsNotNone(link)
        self.assertEqual(link.document_kind, "wiki")
        self.assertEqual(link.document_token, "YNU8wYMwBiJv5AkYQIJcQ4donsh")
        self.assertEqual(link.url, "https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh")

    def test_work_item_source_read_delegates_to_work_item_reader(self):
        class StubWorkItemReader:
            def __init__(self):
                self.gateway_calls = []
                self.openapi_calls = []

            def read_via_gateway(self, link, gateway):
                self.gateway_calls.append((link, gateway))
                return None

            def read_via_open_api_env(self, link):
                self.openapi_calls.append(link)
                return {
                    "read_status": "success",
                    "source_type": "feishu_project_story",
                    "url": link.url,
                    "project_key": link.project_key,
                    "work_item_type_key": link.work_item_type_key,
                    "work_item_id": link.work_item_id,
                    "summary_markdown": "Project 正文",
                }

        work_item_reader = StubWorkItemReader()
        reader = FeishuProjectReader(work_item_reader=work_item_reader)

        context = reader.read_from_text("需求：https://project.feishu.cn/foo/story/detail/123")

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["work_item_id"], "123")
        self.assertEqual(len(work_item_reader.gateway_calls), 1)
        self.assertEqual(len(work_item_reader.openapi_calls), 1)

    def test_document_source_read_delegates_to_document_reader(self):
        class StubDocumentReader:
            def __init__(self):
                self.gateway_calls = []
                self.cli_calls = []

            def read_via_gateway(self, link, gateway):
                self.gateway_calls.append((link, gateway))
                return None

            def read_via_lark_cli(self, link):
                self.cli_calls.append(link)
                return {
                    "read_status": "success",
                    "source_type": "feishu_docx",
                    "url": link.url,
                    "document_kind": link.document_kind,
                    "document_token": link.document_token,
                    "summary_markdown": "文档正文",
                }

        document_reader = StubDocumentReader()
        reader = FeishuProjectReader(document_reader=document_reader)

        context = reader.read_from_text("需求文档：https://bestfulfill.feishu.cn/docx/DocxToken123")

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["document_token"], "DocxToken123")
        self.assertEqual(len(document_reader.gateway_calls), 1)
        self.assertEqual(len(document_reader.cli_calls), 1)


if __name__ == "__main__":
    unittest.main()
