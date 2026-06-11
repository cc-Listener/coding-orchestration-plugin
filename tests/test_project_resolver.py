import unittest

from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class ProjectResolverTest(unittest.TestCase):
    def setUp(self):
        self.registry = ProjectRegistry(
            projects=[
                {
                    "name": "order-system",
                    "aliases": ["订单系统", "OMS"],
                    "path": "/repo/order-system",
                    "keywords": ["订单", "发货", "库存"],
                },
                {
                    "name": "billing-system",
                    "aliases": ["账单系统"],
                    "path": "/repo/billing-system",
                    "keywords": ["订单", "账单", "支付"],
                },
            ]
        )
        self.resolver = ProjectResolver(self.registry)

    def test_explicit_project_wins_with_full_confidence(self):
        result = self.resolver.resolve(
            text="修复发货模块",
            explicit_project="OMS",
        )

        self.assertFalse(result.needs_human)
        self.assertEqual(result.project_name, "order-system")
        self.assertEqual(result.project_path, "/repo/order-system")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.match_evidence[0].source, "explicit")

    def test_alias_exact_match_auto_routes(self):
        result = self.resolver.resolve(text="订单系统发货失败")

        self.assertFalse(result.needs_human)
        self.assertEqual(result.project_name, "order-system")
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_feishu_markdown_escaped_project_slug_auto_routes(self):
        resolver = ProjectResolver(
            ProjectRegistry(
                [
                    {
                        "name": "bps-admin",
                        "aliases": ["bps-admin"],
                        "path": "/repo/bps-admin",
                        "keywords": ["订单列表"],
                    }
                ]
            )
        )

        result = resolver.resolve(text="这是bps\\-admin的一个前端需求，主要改动订单列表")

        self.assertFalse(result.needs_human)
        self.assertEqual(result.project_name, "bps-admin")

    def test_ambiguous_keyword_match_requires_human(self):
        result = self.resolver.resolve(text="订单状态有问题")

        self.assertTrue(result.needs_human)
        self.assertIsNone(result.project_path)
        self.assertGreaterEqual(len(result.candidates), 2)

    def test_keyword_only_match_returns_candidates_for_codex_rerank(self):
        registry = ProjectRegistry(
            [
                {"name": "oms", "path": "/repo/oms", "keywords": ["订单"]},
                {"name": "wms", "path": "/repo/wms", "keywords": ["订单"]},
            ]
        )
        resolver = ProjectResolver(registry)

        result = resolver.resolve("订单状态优化")

        self.assertIsNone(result.project_name)
        self.assertTrue(result.needs_human)
        self.assertEqual([item.project_name for item in result.candidates], ["oms", "wms"])

    def test_no_match_requires_human(self):
        result = self.resolver.resolve(text="修一下首页样式")

        self.assertTrue(result.needs_human)
        self.assertIsNone(result.project_name)
        self.assertEqual(result.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
