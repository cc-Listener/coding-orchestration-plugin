from __future__ import annotations

import unittest
from types import SimpleNamespace

from coding_orchestration import coding_status_command_executor as executor


class FakeLedger:
    def __init__(self, tasks: dict[str, dict]) -> None:
        self.tasks = tasks
        self.get_calls: list[str] = []

    def get_task(self, task_id: str) -> dict | None:
        self.get_calls.append(task_id)
        task = self.tasks.get(task_id)
        return dict(task) if task else None


class FakeStatusHost:
    def __init__(self) -> None:
        self.ledger = FakeLedger(
            {
                "task_1": {"task_id": "task_1", "status": "planned"},
                "task_done": {"task_id": "task_done", "status": "running"},
                "task_child": {"task_id": "task_child", "status": "planned"},
            }
        )
        self.active_task_id = ""
        self.reconcile_results: dict[str, dict | None] = {}
        self.reconcile_calls: list[tuple[str, dict]] = []

    def _reconcile_completed_active_run(self, task_id: str, *, task: dict):
        self.reconcile_calls.append((task_id, task))
        return self.reconcile_results.get(task_id)

    def _format_task_status_details(self, task: dict, *, include_branch: bool) -> str:
        raise AssertionError("host task status presenter proxy should not be used")

    def _active_task_id_for_event(self, event) -> str:
        return self.active_task_id


class CodingStatusCommandExecutorTest(unittest.TestCase):
    def test_command_status_requires_task_id_and_reports_missing_task_without_reconcile(self):
        host = FakeStatusHost()

        self.assertEqual(executor.command_coding_status(host, ""), "请提供任务 ID。")
        self.assertEqual(executor.command_coding_status(host, "missing"), "未找到任务：missing")

        self.assertEqual(host.reconcile_calls, [])

    def test_command_status_reconciles_completed_active_run_before_formatting_without_branch(self):
        host = FakeStatusHost()
        host.reconcile_results["task_done"] = {"run_id": "run_done"}

        message = executor.command_coding_status(host, "task_done")

        self.assertIn("[task_done] 已自动回收后台执行：run_done", message)
        self.assertIn("[task_done] 状态：运行中(running)", message)
        self.assertNotIn("源分支：", message)
        self.assertEqual(host.reconcile_calls[0][0], "task_done")

    def test_command_status_delegates_delivery_flags_after_reconcile_gate(self):
        host = FakeStatusHost()
        calls = []
        original = executor.delivery_command_executor.command_coding_delivery_status
        executor.delivery_command_executor.command_coding_delivery_status = (
            lambda passed_host, *, task_id, task, tree_view: calls.append(
                (passed_host, task_id, task["task_id"], tree_view)
            )
            or "delivery-status"
        )
        try:
            message = executor.command_coding_status(host, "task_child --tree")
        finally:
            executor.delivery_command_executor.command_coding_delivery_status = original

        self.assertEqual(message, "delivery-status")
        self.assertEqual(calls, [(host, "task_child", "task_child", True)])
        self.assertEqual(host.reconcile_calls[0][0], "task_child")

    def test_gateway_status_uses_active_task_fallback_and_formats_with_branch(self):
        host = FakeStatusHost()
        host.active_task_id = "task_1"

        message = executor.status_for_event(host, "", SimpleNamespace())

        self.assertEqual(
            message,
            "[task_1] 状态：已规划(planned)\n"
            "项目：未确定\n"
            "源分支：未创建\n"
            "工作区：未创建",
        )

    def test_gateway_status_with_flags_reuses_command_status_path(self):
        host = FakeStatusHost()
        host.active_task_id = "task_child"
        calls = []
        original = executor.delivery_command_executor.command_coding_delivery_status
        executor.delivery_command_executor.command_coding_delivery_status = (
            lambda passed_host, *, task_id, task, tree_view: calls.append(
                (passed_host, task_id, task["task_id"], tree_view)
            )
            or "delivery-status"
        )
        try:
            message = executor.status_for_event(host, "--delivery", SimpleNamespace())
        finally:
            executor.delivery_command_executor.command_coding_delivery_status = original

        self.assertEqual(message, "delivery-status")
        self.assertEqual(calls, [(host, "task_child", "task_child", False)])


if __name__ == "__main__":
    unittest.main()
