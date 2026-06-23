from __future__ import annotations

import unittest

from coding_orchestration.presenters import feedback_presenter


class FeedbackPresenterTest(unittest.TestCase):
    def test_missing_feedback_media_message_explains_recovery(self):
        message = feedback_presenter.missing_feedback_media_message(
            {"task_id": "task_media"},
            "bugfix",
        )

        self.assertIn("[task_media] 未启动 Codex", message)
        self.assertIn("图片未捕获", message)
        self.assertIn("请重发图片或图片链接", message)
        self.assertIn("/coding bugfix <反馈>", message)

    def test_plan_feedback_messages_are_stable(self):
        task = {"task_id": "task_plan", "project_path": "/tmp/order"}

        normal = feedback_presenter.plan_feedback_received_message(task)
        blocked = feedback_presenter.blocked_plan_feedback_received_message(task)

        self.assertIn("已收到计划反馈，重新整理计划", normal)
        self.assertIn("不会直接改代码", normal)
        self.assertIn("已收到受阻计划的补充信息", blocked)
        self.assertIn("上一次计划仍受阻", blocked)
        self.assertIn("不会直接开始实现", blocked)

    def test_requirement_change_messages_are_stable(self):
        task = {"task_id": "task_change", "project_path": "/tmp/order"}

        received = feedback_presenter.requirement_change_received_message(task)
        queued = feedback_presenter.requirement_change_queued_message(task)

        self.assertIn("已收到需求变更", received)
        self.assertIn("变更影响", received)
        self.assertIn("不直接开始修复", received)
        self.assertIn("已记录需求变更，但当前任务仍在执行", queued)
        self.assertIn("暂不启动新的计划", queued)

    def test_implementation_and_runtime_feedback_messages_are_stable(self):
        task = {"task_id": "task_fix", "project_path": "/tmp/order"}

        implementation = feedback_presenter.implementation_feedback_received_message(task)
        runtime = feedback_presenter.runtime_feedback_received_message(task)

        self.assertIn("已收到修复反馈，开始修复", implementation)
        self.assertIn("复用该任务最近一次实现工作区", implementation)
        self.assertIn("任务正在运行，已记录本次反馈", runtime)
        self.assertIn("当前执行不会并发重启", runtime)

    def test_human_clarification_messages_are_stable(self):
        unresolved = feedback_presenter.human_clarification_received_message(
            {"task_id": "task_human"}
        )
        resolved = feedback_presenter.human_clarification_project_resolved_message(
            {"task_id": "task_human", "project_path": "/tmp/order"}
        )

        self.assertIn("已收到补充信息，仍需要继续确认", unresolved)
        self.assertIn("项目：未确定", unresolved)
        self.assertIn("已补充项目上下文，开始整理计划", resolved)
        self.assertIn("项目：/tmp/order", resolved)


if __name__ == "__main__":
    unittest.main()
