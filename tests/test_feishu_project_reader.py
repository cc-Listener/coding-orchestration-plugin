import unittest

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


if __name__ == "__main__":
    unittest.main()
