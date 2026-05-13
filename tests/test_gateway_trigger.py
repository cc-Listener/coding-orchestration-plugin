import unittest

from coding_orchestration.orchestrator import CodingOrchestrator


class GatewayTriggerTest(unittest.TestCase):
    def test_plain_bug_or_requirement_words_do_not_trigger_gateway_hook(self):
        self.assertFalse(CodingOrchestrator._looks_like_task("帮我看下这个 bug"))
        self.assertFalse(CodingOrchestrator._looks_like_task("这个需求晚点再聊"))
        self.assertFalse(CodingOrchestrator._looks_like_task("修复一下群公告文案"))

    def test_project_scoped_natural_requirement_triggers_gateway_hook(self):
        self.assertTrue(
            CodingOrchestrator._looks_like_task("BPS运营后台有个需求，在策略列表上，新增一个状态筛选")
        )
        self.assertTrue(CodingOrchestrator._looks_like_task("订单系统新增一个发货状态筛选"))

    def test_explicit_coding_commands_trigger_gateway_hook(self):
        self.assertTrue(CodingOrchestrator._looks_like_task("/coding-task --project 订单系统 修复发货"))
        self.assertTrue(CodingOrchestrator._looks_like_task("/codex-task --project 订单系统 写计划"))
        self.assertTrue(CodingOrchestrator._looks_like_task("编码任务：修复订单发货失败"))
        self.assertTrue(CodingOrchestrator._looks_like_task("https://project.feishu.cn/example/issue/123"))


if __name__ == "__main__":
    unittest.main()
