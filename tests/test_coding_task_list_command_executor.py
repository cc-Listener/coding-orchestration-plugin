import unittest

from coding_orchestration import coding_task_list_command_executor


class FakeLedger:
    def __init__(self, tasks):
        self.tasks = tasks
        self.calls = []

    def list_recent_tasks(self, *, statuses=None, limit=None):
        self.calls.append({"statuses": statuses, "limit": limit})
        return list(self.tasks)


class FakeHost:
    def __init__(self, tasks, *, active_id=None, binding_key="chat:user"):
        self.ledger = FakeLedger(tasks)
        self.active_id = active_id
        self.binding_key = binding_key

    def _active_coding_statuses(self):
        return ["planned", "blocked", "merged_test"]

    def _active_task_id_for_event(self, event):
        return self.active_id

    def _binding_key_for_event(self, event):
        return self.binding_key


class CodingTaskListCommandExecutorTest(unittest.TestCase):
    def test_command_coding_list_uses_active_statuses_and_formats_tasks(self):
        host = FakeHost(
            [
                {
                    "task_id": "task_1",
                    "status": "blocked",
                    "source": {"project_name": "bps-admin"},
                    "requirement_summary": "订单流列表增加筛选操作按钮",
                }
            ]
        )

        message = coding_task_list_command_executor.command_coding_list(host, "")

        self.assertEqual(host.ledger.calls, [{"statuses": ["planned", "blocked", "merged_test"], "limit": 20}])
        self.assertIn("任务：task_1", message)
        self.assertIn("状态：受阻(blocked)", message)
        self.assertIn("项目：bps-admin", message)
        self.assertIn("任务描述：订单流列表增加筛选操作按钮", message)

    def test_command_coding_list_returns_empty_message(self):
        host = FakeHost([])

        message = coding_task_list_command_executor.command_coding_list(host, "")

        self.assertEqual(message, "当前没有未结束开发任务。")

    def test_task_list_for_event_marks_active_task_and_adds_binding_tip(self):
        host = FakeHost(
            [
                {
                    "task_id": "task_1",
                    "status": "merged_test",
                    "source": {"project_name": "bps-admin"},
                    "requirement_summary": "订单列表筛选操作",
                }
            ],
            active_id="task_1",
            binding_key="chat:user",
        )

        message = coding_task_list_command_executor.task_list_for_event(host, event=object())

        self.assertEqual(host.ledger.calls, [{"statuses": ["planned", "blocked", "merged_test"], "limit": 10}])
        self.assertIn("任务：*task_1", message)
        self.assertIn("提示：当前会话绑定：task_1；使用 /coding use <task_id> 切换当前任务。", message)

    def test_task_list_for_event_without_binding_key_adds_generic_tip(self):
        host = FakeHost(
            [
                {
                    "task_id": "task_1",
                    "status": "blocked",
                    "source": {"project_name": "bps-admin"},
                    "requirement_summary": "订单列表筛选操作",
                }
            ],
            active_id=None,
            binding_key=None,
        )

        message = coding_task_list_command_executor.task_list_for_event(host, event=object())

        self.assertIn("任务：task_1", message)
        self.assertIn("提示：使用 /coding use <task_id> 切换当前任务。", message)


if __name__ == "__main__":
    unittest.main()
