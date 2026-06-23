import unittest

from coding_orchestration.source.source_links import extract_feishu_project_link, extract_meegle_link
from coding_orchestration.source.source_work_item_context import (
    coerce_work_item_context,
    normalize_work_item_payload,
)


class SourceWorkItemContextTest(unittest.TestCase):
    def test_normalizes_payload_without_guessing_description(self):
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")

        context = normalize_work_item_payload(
            link,
            {
                "data": {
                    "work_item": {
                        "name": "订单状态优化",
                        "fields": [
                            {"field_name": "需求描述", "field_value": "优化订单状态展示"},
                            {"field_name": "验收标准", "field_value": "状态准确"},
                        ],
                    }
                }
            },
            heading="飞书 Project 需求",
        )

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["source_type"], "feishu_project_story")
        self.assertEqual(context["raw_fields"][0]["name"], "需求描述")
        self.assertEqual(context["raw_fields"][1]["value"], "状态准确")
        self.assertNotIn("description", context)
        self.assertNotIn("fields", context)
        self.assertIn("## 飞书 Project 需求", context["summary_markdown"])
        self.assertIn("请在 plan 阶段从 raw_fields 中提取需求", context["summary_markdown"])

    def test_summary_heading_is_adapter_specific(self):
        link = extract_meegle_link("https://project.feishu.cn/foo/story/detail/123")

        context = normalize_work_item_payload(
            link,
            {"data": {"work_item": {"name": "订单状态优化", "fields": []}}},
            heading="Meegle / 飞书 Project 需求",
        )

        self.assertIn("## Meegle / 飞书 Project 需求", context["summary_markdown"])
        self.assertIn("未返回可用字段", context["summary_markdown"])

    def test_coerce_context_preserves_existing_success_context(self):
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")

        context = coerce_work_item_context(
            link,
            {"read_status": "success", "summary_markdown": "已有正文", "title": "已有标题"},
            normalize_payload=lambda link, value: {},
            failed_context=lambda link, error: {"read_status": "failed", "error": error},
            api_label="Feishu Project API",
        )

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["source_type"], "feishu_project_story")
        self.assertEqual(context["summary_markdown"], "已有正文")
        self.assertEqual(context["title"], "已有标题")

    def test_coerce_context_maps_failed_status_to_failed_context(self):
        link = extract_meegle_link("https://project.feishu.cn/foo/story/detail/123")

        context = coerce_work_item_context(
            link,
            {"read_status": "failed", "error": "permission missing"},
            normalize_payload=lambda link, value: {},
            failed_context=lambda link, error: {"read_status": "failed", "error": error},
            api_label="Meegle API",
            failed_status_error="Meegle read failed.",
        )

        self.assertEqual(context, {"read_status": "failed", "error": "permission missing"})

    def test_coerce_context_maps_nonzero_code_to_adapter_error(self):
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")

        context = coerce_work_item_context(
            link,
            {"code": 403, "msg": "forbidden"},
            normalize_payload=lambda link, value: {},
            failed_context=lambda link, error: {"read_status": "failed", "error": error},
            api_label="Feishu Project API",
        )

        self.assertEqual(
            context,
            {"read_status": "failed", "error": "Feishu Project API returned code=403: forbidden"},
        )


if __name__ == "__main__":
    unittest.main()
