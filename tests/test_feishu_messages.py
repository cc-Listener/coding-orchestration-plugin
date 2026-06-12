import unittest

from coding_orchestration.feishu_messages import (
    render_task_created,
    render_task_needs_human,
    render_task_needs_source_context,
)
from coding_orchestration.models import ProjectCandidate


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
        self.assertEqual(message.count("task_1"), 2)
        self.assertIn("订单列表新增店铺筛选", message)
        self.assertIn("项目：bps-admin (/repo/bps-admin)", message)
        self.assertIn("发送 /coding run task_1 开始整理计划。", message)
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

        self.assertIn("已自动开始实现", message)
        self.assertIn("轻量改动", message)
        self.assertIn("简单 UI 行为", message)
        self.assertIn("/coding cancel task_2", message)
        self.assertNotIn("implementation 已自动启动", message)
        self.assertNotIn("plan-only", message)

    def test_needs_human_message_uses_actionable_user_copy(self):
        message = render_task_needs_human(
            "task_3",
            "订单列表新增店铺筛选",
            [
                ProjectCandidate(
                    project_name="bps-admin",
                    project_path="/repo/bps-admin",
                    confidence=0.66,
                )
            ],
        )

        self.assertIn("任务需要人工确认", message)
        self.assertIn("/coding task --project", message)
        self.assertIn("/coding project init", message)
        self.assertNotIn("LLM Wiki", message)
        self.assertNotIn("project_profile", message)

    def test_source_context_message_hides_internal_reader_details(self):
        message = render_task_needs_source_context(
            "task_4",
            "按飞书文档实现订单筛选",
            "https://bestfulfill.feishu.cn/wiki/example",
            "授权已过期。",
        )

        self.assertIn("飞书来源暂时还不能自动读取", message)
        self.assertIn("授权飞书文档读取", message)
        self.assertNotIn("Codex plan", message)
        self.assertNotIn("lark-cli", message)


if __name__ == "__main__":
    unittest.main()
