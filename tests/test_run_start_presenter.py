from __future__ import annotations

import unittest

from coding_orchestration import run_start_presenter
from coding_orchestration.models import RunMode, TaskStatus


class RunStartPresenterTest(unittest.TestCase):
    def test_plan_implementation_and_qa_started_messages_are_stable(self):
        task = {"task_id": "task_run", "project_path": "/tmp/order"}

        plan = run_start_presenter.plan_only_started_message(task)
        implementation = run_start_presenter.implementation_started_message(task)
        qa = run_start_presenter.qa_started_message(task)

        self.assertIn("[task_run] 已开始整理计划。", plan)
        self.assertIn("完成后会自动回传结果", plan)
        self.assertIn("[task_run] 已收到确认，开始实现。", implementation)
        self.assertIn("不会自动进入测试、合并或发布", implementation)
        self.assertIn("[task_run] 已开始 QA。", qa)
        self.assertIn("不会自动 merge-test 或发布", qa)

    def test_implementation_blocked_before_plan_ready_message_uses_status_display(self):
        message = run_start_presenter.implementation_blocked_before_plan_ready_message(
            {"task_id": "task_new", "status": TaskStatus.NEW.value}
        )

        self.assertIn("已拦截实现确认", message)
        self.assertIn("状态：新建(new)", message)
        self.assertIn("必须先完成计划", message)

    def test_active_run_message_includes_active_run_and_recovery_action(self):
        task = {
            "task_id": "task_active",
            "status": TaskStatus.RUNNING.value,
            "task_session": {
                "runner": {
                    "active_run_id": "run_active",
                    "active_mode": RunMode.QA.value,
                }
            },
        }

        message = run_start_presenter.active_run_already_running_message(
            task,
            requested_mode=RunMode.PLAN_ONLY.value,
        )

        self.assertIn("当前已有执行正在进行，未重复启动整理计划。", message)
        self.assertIn("状态：运行中(running)", message)
        self.assertIn("当前执行：run_active", message)
        self.assertIn("执行模式：QA 验证", message)
        self.assertIn("/coding status task_active", message)

    def test_cannot_start_run_message_has_reason_and_recovery_action(self):
        message = run_start_presenter.cannot_start_run_message(
            {"task_id": "task_done", "status": TaskStatus.DONE.value},
            mode=RunMode.IMPLEMENTATION,
            reason="invalid task transition done -> running",
        )

        self.assertIn("当前状态为 已完成(done)，不能启动实现执行", message)
        self.assertIn("原因：invalid task transition done -> running", message)
        self.assertIn("恢复动作：如需重新处理", message)


if __name__ == "__main__":
    unittest.main()
