import unittest

from coding_orchestration.source.adapters.meegle_reader import MeegleReader
from coding_orchestration.source_resolver import SourceResolver


def missing_command_runner(command):
    raise FileNotFoundError(command[0])


class FakeMeegleReader:
    def read_from_text(self, text, gateway=None):
        return {
            "read_status": "failed",
            "source_type": "feishu_project_story",
            "url": text,
            "deferred_source_resolution": True,
            "requires_human_context": False,
        }


class FakeFeishuReader:
    def read_from_text(self, text, gateway=None):
        return {"read_status": "success", "source_type": "feishu_docx", "url": text}


class MeegleReaderTest(unittest.TestCase):
    def test_meegle_reader_extracts_project_work_item_url(self):
        link = MeegleReader.extract_first_link("https://project.feishu.cn/z9b9t3/story/detail/6983769492")

        self.assertIsNotNone(link)
        self.assertEqual(link.project_key, "z9b9t3")
        self.assertEqual(link.work_item_type_key, "story")
        self.assertEqual(link.work_item_id, "6983769492")

    def test_meegle_missing_cli_returns_deferred_not_human_blocked(self):
        reader = MeegleReader(command_runner=missing_command_runner)

        context = reader.read_from_text("https://project.feishu.cn/z9b9t3/story/detail/6983769492")

        self.assertEqual(context["read_status"], "failed")
        self.assertTrue(context["deferred_source_resolution"])
        self.assertFalse(context["requires_human_context"])

    def test_meegle_reader_preserves_raw_fields_without_guessing_description(self):
        reader = MeegleReader()
        link = MeegleReader.extract_first_link("https://project.feishu.cn/foo/story/detail/123")
        payload = {
            "data": {
                "work_item": {
                    "name": "订单状态优化",
                    "fields": [
                        {"field_name": "需求描述", "field_value": "优化订单状态展示"},
                        {"field_name": "验收标准", "field_value": "状态准确"},
                    ],
                }
            }
        }

        context = reader.normalize_payload(link, payload)

        self.assertEqual(context["raw_fields"][0]["name"], "需求描述")
        self.assertEqual(context["raw_fields"][1]["name"], "验收标准")
        self.assertNotIn("description", context)
        self.assertNotIn("fields", context)
        self.assertIn("### 原始字段", context["summary_markdown"])
        self.assertIn("请在 plan 阶段从 raw_fields 中提取需求", context["summary_markdown"])

    def test_meegle_reader_empty_raw_fields_summary_is_explicit(self):
        reader = MeegleReader()
        link = MeegleReader.extract_first_link("https://project.feishu.cn/foo/story/detail/123")

        context = reader.normalize_payload(
            link,
            {"data": {"work_item": {"name": "订单状态优化", "fields": []}}},
        )

        self.assertEqual(context["raw_fields"], [])
        self.assertIn("### 原始字段", context["summary_markdown"])
        self.assertIn("未返回可用字段", context["summary_markdown"])

    def test_source_resolver_routes_project_links_to_meegle_reader(self):
        resolver = SourceResolver(meegle_reader=FakeMeegleReader(), feishu_reader=FakeFeishuReader())

        context = resolver.resolve_source(
            {"url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492"}
        )

        self.assertEqual(context["source_type"], "feishu_project_story")
        self.assertTrue(context["deferred_source_resolution"])


if __name__ == "__main__":
    unittest.main()
