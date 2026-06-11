import unittest

from coding_orchestration.feishu_messages import render_task_created


class FeishuMessagesTest(unittest.TestCase):
    def test_task_created_uses_user_copy_without_internal_debug_fields(self):
        message = render_task_created(
            "task_1",
            "订单列表新增店铺筛选",
            "bps-admin",
            "/repo/bps-admin",
            status="planned",
            phase="draft",
        )

        self.assertIn("已记录新任务", message)
        self.assertNotIn("已创建编码任务", message)
        self.assertIn("任务：task_1", message)
        self.assertEqual(message.count("task_1"), 1)
        self.assertIn("订单列表新增店铺筛选", message)
        self.assertIn("项目：bps-admin (/repo/bps-admin)", message)
        self.assertIn("进入 plan-only。", message)
        self.assertNotIn("任务ID：", message)
        self.assertNotIn("调试信息", message)
        self.assertNotIn("status=", message)
        self.assertNotIn("phase=", message)
        self.assertNotIn("当前状态：", message)
        self.assertNotIn("status:", message)
        self.assertNotIn("recovery_action", message)

    def test_inline_implementation_notice_stays_visible(self):
        message = render_task_created(
            "task_2",
            "修复按钮样式",
            "web-app",
            "/repo/web-app",
            status="running",
            phase="implementing",
            auto_implementation_started=True,
            execution_policy={"route": "fast_fix", "planning": "inline", "reasons": ["small_ui_behavior"]},
        )

        self.assertIn("implementation 已自动启动", message)
        self.assertIn("已跳过 plan-only", message)
        self.assertIn("简单 UI 行为", message)
        self.assertIn("/coding cancel task_2", message)


if __name__ == "__main__":
    unittest.main()
