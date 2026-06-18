from __future__ import annotations

import unittest

from coding_orchestration import gateway_rewrite_presenter
from coding_orchestration.models import TaskStatus


class GatewayRewritePresenterTest(unittest.TestCase):
    def test_confirmation_message_includes_command_reason_and_reply_hint(self):
        message = gateway_rewrite_presenter.format_rewrite_confirmation_message(
            "/coding delete task_123",
            {"reason": "用户明确要求删除任务"},
        )

        self.assertIn("我理解你要执行：", message)
        self.assertIn("/coding delete task_123", message)
        self.assertIn("理由：用户明确要求删除任务", message)
        self.assertIn("回复“确认”执行，或回复“取消”放弃。", message)

    def test_needs_human_message_sanitizes_internal_rejection(self):
        message = gateway_rewrite_presenter.format_rewrite_needs_human_confirmation_message(
            "帮我处理一下",
            {"canonical_command": None, "confidence": 0.12},
            "置信度 0.12 低于阈值 0.85。",
        )

        self.assertIn("我还不能确定要执行哪个 coding 动作", message)
        self.assertIn("需要补充：请补充项目、任务目标或要执行的动作。", message)
        self.assertNotIn("置信度", message)
        self.assertNotIn("阈值", message)

    def test_handoff_message_projects_task_context_without_internal_json(self):
        message = gateway_rewrite_presenter.format_rewrite_handoff_to_hermes_message(
            "这个先讨论下",
            {
                "active_project": {"name": "bps-admin"},
                "active_task": {
                    "task_id": "task_abc",
                    "status": TaskStatus.PLANNED.value,
                    "status_label": "计划已就绪",
                    "project": "bps-admin",
                    "summary": "优化订单列表查询",
                    "next_step": "/coding implement task_abc",
                },
                "known_tasks": [
                    {
                        "task_id": "task_abc",
                        "status": TaskStatus.PLANNED.value,
                        "summary": "优化订单列表查询",
                    }
                ],
            },
            "缺少要执行的动作",
        )

        self.assertIn("当前项目：bps-admin", message)
        self.assertIn("当前任务：task_abc，状态 计划已就绪，项目 bps-admin，摘要：优化订单列表查询", message)
        self.assertIn("当前任务建议下一步：/coding implement task_abc", message)
        self.assertIn("最近相关任务：task_abc（已规划(planned)）：优化订单列表查询", message)
        self.assertIn("可用入口：/coding task --project", message)
        self.assertNotIn("上下文 JSON", message)
        self.assertNotIn("active_project", message)


if __name__ == "__main__":
    unittest.main()
