import unittest

from coding_orchestration.feishu_work_item_reader import FeishuWorkItemReader
from coding_orchestration.source_links import extract_feishu_project_link


class FeishuWorkItemReaderTest(unittest.TestCase):
    def test_normalizes_work_item_payload_to_codex_context(self):
        reader = FeishuWorkItemReader()
        link = extract_feishu_project_link(
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
        self.assertEqual(context["raw_fields"][0]["name"], "需求描述")
        self.assertEqual(context["raw_fields"][1]["name"], "状态")
        self.assertNotIn("description", context)
        self.assertNotIn("fields", context)
        self.assertIn("BPS 订单列表新增店铺筛选", context["summary_markdown"])
        self.assertIn("### 原始字段", context["summary_markdown"])
        self.assertIn("订单列表需要支持按店铺筛选", context["summary_markdown"])
        self.assertIn("状态", context["summary_markdown"])
        self.assertIn("请在 plan 阶段从 raw_fields 中提取需求", context["summary_markdown"])

    def test_preserves_raw_fields_without_guessing_description(self):
        reader = FeishuWorkItemReader()
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")
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

    def test_empty_raw_fields_summary_is_explicit(self):
        reader = FeishuWorkItemReader()
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")

        context = reader.normalize_payload(
            link,
            {"data": {"work_item": {"name": "订单状态优化", "fields": []}}},
        )

        self.assertEqual(context["raw_fields"], [])
        self.assertIn("### 原始字段", context["summary_markdown"])
        self.assertIn("未返回可用字段", context["summary_markdown"])

    def test_gateway_reader_normalizes_payload_result(self):
        class Gateway:
            def __init__(self):
                self.calls = []

            def read_feishu_project_work_item(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "data": {
                        "work_item": {
                            "name": "网关需求",
                            "fields": [{"field_name": "状态", "field_value": "待开发"}],
                        }
                    }
                }

        gateway = Gateway()
        reader = FeishuWorkItemReader()
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")

        context = reader.read_via_gateway(link, gateway)

        self.assertEqual(context["title"], "网关需求")
        self.assertEqual(context["raw_fields"][0]["name"], "状态")
        self.assertEqual(
            gateway.calls,
            [
                {
                    "project_key": "foo",
                    "work_item_type_key": "story",
                    "work_item_id": "123",
                    "url": "https://project.feishu.cn/foo/story/detail/123",
                }
            ],
        )

    def test_open_api_env_reader_uses_injected_env_and_opener(self):
        requests = []

        def env_getter(name):
            values = {
                "FEISHU_PROJECT_PLUGIN_TOKEN": "plugin-token",
                "FEISHU_PROJECT_USER_KEY": "user-key",
                "FEISHU_PROJECT_WORK_ITEM_DETAIL_URL_TEMPLATE": (
                    "https://example.test/{project_key}/{work_item_type_key}/{work_item_id}"
                ),
            }
            return values.get(name)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data":{"work_item":{"name":"OpenAPI \\u9700\\u6c42","fields":[]}}}'

        def opener(request, timeout):
            requests.append((request, timeout))
            return Response()

        reader = FeishuWorkItemReader(env_getter=env_getter, opener=opener)
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")

        context = reader.read_via_open_api_env(link)

        self.assertEqual(context["title"], "OpenAPI 需求")
        self.assertEqual(requests[0][0].full_url, "https://example.test/foo/story/123")
        self.assertEqual(requests[0][1], 15)

    def test_open_api_env_reader_returns_none_without_token(self):
        reader = FeishuWorkItemReader(env_getter=lambda name: None)
        link = extract_feishu_project_link("https://project.feishu.cn/foo/story/detail/123")

        self.assertIsNone(reader.read_via_open_api_env(link))


if __name__ == "__main__":
    unittest.main()
