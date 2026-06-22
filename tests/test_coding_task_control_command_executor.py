import unittest

from coding_orchestration import coding_task_control_command_executor
from coding_orchestration.models import TaskPhase, TaskStatus


class FakeLedger:
    def __init__(self, tasks=None):
        self.tasks = dict(tasks or {})
        self.cancelled_runs = set()
        self.session_updates = []
        self.human_decisions = []
        self.deleted = []

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def mark_cancelled(self, run_id):
        if run_id == "run_1":
            self.cancelled_runs.add(run_id)
            return True
        return False

    def update_task_session(self, task_id, update):
        self.session_updates.append((task_id, update))

    def append_human_decision(self, task_id, decision):
        self.human_decisions.append((task_id, decision))

    def delete_task(self, task_id):
        if task_id not in self.tasks:
            return False
        self.deleted.append(task_id)
        del self.tasks[task_id]
        return True


class FakeWiki:
    def __init__(self):
        self.deleted_task_ids = []

    def delete_by_source_task(self, task_id):
        self.deleted_task_ids.append(task_id)
        return 2


class FakeBindingService:
    def __init__(self):
        self.clear_result = False

    def clear_active_task_for_event(self, event):
        return self.clear_result


class FakeHost:
    def __init__(self, tasks=None):
        self.ledger = FakeLedger(tasks)
        self.wiki = FakeWiki()
        self.gateway_binding_service = FakeBindingService()
        self.bind_result = True
        self.binding_key = "chat:1"
        self.mode_cleared = False
        self.pending_rewrite_cleared = False
        self.pending_action_cleared = False
        self.transitions = []
        self.transition_error = None
        self.purged = []

    def _bind_active_task_for_event(self, task_id, event):
        return self.bind_result

    def _binding_key_for_event(self, event):
        return self.binding_key

    def _disable_coding_mode_for_event(self, event):
        return self.mode_cleared

    def _clear_pending_rewrite_for_event(self, event):
        return self.pending_rewrite_cleared

    def _clear_pending_action_for_event(self, event):
        return self.pending_action_cleared

    def _transition_task_status(self, task_id, status, *, phase, reason):
        if self.transition_error is not None:
            raise self.transition_error
        self.transitions.append((task_id, status, phase, reason))
        task = self.ledger.tasks[task_id]
        task["status"] = status.value
        task["phase"] = phase.value

    def _task_is_cancelled(self, task):
        return task.get("status") == TaskStatus.CANCELLED.value

    def _restore_state_for_cancelled_task(self, task):
        return TaskStatus.PLANNED, TaskPhase.PLAN_READY, "最近 plan-only 已完成"

    def _purge_task_artifacts(self, task):
        self.purged.append(task["task_id"])
        return ["/tmp/run", "/tmp/workspace"]


class CodingTaskControlCommandExecutorTest(unittest.TestCase):
    def test_command_use_and_exit_are_gateway_binding_only_in_command_mode(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": TaskStatus.PLANNED.value}})

        self.assertIn("命令模式缺少飞书来源", coding_task_control_command_executor.command_coding_use(host, ""))
        self.assertEqual(coding_task_control_command_executor.command_coding_use(host, "missing"), "未找到任务：missing")
        self.assertIn("任务存在", coding_task_control_command_executor.command_coding_use(host, "task_1"))
        self.assertIn("命令模式缺少飞书来源", coding_task_control_command_executor.command_coding_exit(host, ""))

    def test_gateway_select_and_clear_active_task_use_binding_callbacks(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": TaskStatus.PLANNED.value}})

        self.assertIn("请提供任务 ID", coding_task_control_command_executor.select_active_task_for_event(host, "", object()))
        self.assertEqual(
            coding_task_control_command_executor.select_active_task_for_event(host, "missing", object()),
            "未找到任务：missing",
        )
        host.bind_result = False
        self.assertIn("无法绑定任务", coding_task_control_command_executor.select_active_task_for_event(host, "task_1", object()))
        host.bind_result = True
        self.assertIn("已切换当前开发任务", coding_task_control_command_executor.select_active_task_for_event(host, "task_1", object()))

        host.binding_key = None
        self.assertIn("当前来源无法识别", coding_task_control_command_executor.clear_active_task_for_event(host, object()))
        host.binding_key = "chat:1"
        host.gateway_binding_service.clear_result = True
        self.assertIn("已退出当前飞书会话", coding_task_control_command_executor.clear_active_task_for_event(host, object()))

    def test_cancel_marks_task_or_run_id_without_bypassing_transition(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": TaskStatus.PLANNED.value}})

        self.assertEqual(coding_task_control_command_executor.command_coding_cancel(host, ""), "请提供任务 ID 或执行 ID。")
        self.assertEqual(coding_task_control_command_executor.command_coding_cancel(host, "task_1"), "已标记取消：task_1")
        self.assertEqual(host.transitions[0][1], TaskStatus.CANCELLED)
        self.assertEqual(coding_task_control_command_executor.command_coding_cancel(host, "run_1"), "已标记取消：run_1")
        self.assertEqual(coding_task_control_command_executor.command_coding_cancel(host, "missing"), "未找到可取消对象：missing")

        error_host = FakeHost({"task_2": {"task_id": "task_2", "status": TaskStatus.DONE.value}})
        error_host.transition_error = ValueError("invalid transition")
        self.assertIn("不能取消", coding_task_control_command_executor.command_coding_cancel(error_host, "task_2"))

    def test_restore_cancelled_task_clears_active_runner_and_records_decision(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": TaskStatus.CANCELLED.value}})

        message = coding_task_control_command_executor.command_coding_restore(host, "task_1")

        self.assertIn("已恢复误取消", message)
        self.assertEqual(host.transitions[0][1], TaskStatus.PLANNED)
        self.assertEqual(host.ledger.session_updates[0][1]["runner"], {"active_run_id": None, "active_mode": None})
        self.assertEqual(host.ledger.human_decisions[0][1]["type"], "task_restored")

        not_cancelled = FakeHost({"task_2": {"task_id": "task_2", "status": TaskStatus.PLANNED.value}})
        self.assertIn("不需要恢复", coding_task_control_command_executor.command_coding_restore(not_cancelled, "task_2"))

    def test_delete_uses_host_artifact_purge_callback_and_delete_gates(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": TaskStatus.RUNNING.value}})

        self.assertIn("正在运行", coding_task_control_command_executor.command_coding_delete(host, "task_1"))

        message = coding_task_control_command_executor.command_coding_delete(host, "task_1 --force")

        self.assertIn("已删除开发任务", message)
        self.assertEqual(host.purged, ["task_1"])
        self.assertEqual(host.wiki.deleted_task_ids, ["task_1"])
        self.assertEqual(host.ledger.deleted, ["task_1"])

    def test_complete_only_allows_merged_test_tasks(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": TaskStatus.PLANNED.value}})

        self.assertIn("不能标记完成", coding_task_control_command_executor.command_coding_complete(host, "task_1"))

        merged = FakeHost({"task_2": {"task_id": "task_2", "status": TaskStatus.MERGED_TEST.value, "phase": TaskPhase.MERGED_TEST.value}})
        message = coding_task_control_command_executor.command_coding_complete(merged, "task_2")

        self.assertIn("已人工标记完成", message)
        self.assertEqual(merged.transitions[0][1], TaskStatus.DONE)
        self.assertEqual(merged.ledger.human_decisions[0][1]["type"], "task_completed")


if __name__ == "__main__":
    unittest.main()
