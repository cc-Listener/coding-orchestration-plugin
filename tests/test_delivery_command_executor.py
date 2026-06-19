from __future__ import annotations

import unittest
from typing import Any

from coding_orchestration import delivery_command_executor
from coding_orchestration.services.delivery_service import DeliveryService


class RecordingLedger:
    def __init__(self, task: dict[str, Any] | None):
        self.task = task
        self.children: dict[str, dict[str, Any]] = {}
        self.list_child_task_ids: list[str] = []
        self.created_task_ids: list[str] = []

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        if self.task is not None and task_id == self.task["task_id"]:
            return self.task
        return self.children.get(task_id)

    def list_child_tasks(self, task_id: str) -> list[dict[str, Any]]:
        self.list_child_task_ids.append(task_id)
        return list(self.children.values())

    def create_task(self, **kwargs: Any) -> None:
        self.created_task_ids.append(str(kwargs["task_id"]))
        self.children[str(kwargs["task_id"])] = {
            "task_id": kwargs["task_id"],
            "requirement_summary": kwargs["requirement_summary"],
        }


class RecordingHost:
    def __init__(self, ledger: RecordingLedger):
        self.ledger = ledger
        self.delivery_service = DeliveryService()
        self.start_run_called = False
        self.implement_called = False

    def start_run(self, *args: Any, **kwargs: Any) -> None:
        self.start_run_called = True

    def command_coding_implement(self, *args: Any, **kwargs: Any) -> str:
        self.implement_called = True
        return ""


class DeliveryCommandExecutorTest(unittest.TestCase):
    def test_materialize_reports_user_facing_validation_errors(self):
        cases = [
            (
                "",
                RecordingHost(RecordingLedger(None)),
                "请提供要生成执行任务的需求 ID。用法：/coding materialize <task_id>",
            ),
            (
                "missing",
                RecordingHost(RecordingLedger(None)),
                "未找到任务：missing",
            ),
            (
                "req_1",
                RecordingHost(RecordingLedger({"task_id": "req_1", "human_decisions": []})),
                "[req_1] 拆解方案还未确认。请先发送 /coding approve-breakdown req_1。",
            ),
            (
                "req_1",
                RecordingHost(
                    RecordingLedger(
                        {
                            "task_id": "req_1",
                            "human_decisions": [{"type": "breakdown_approved"}],
                            "task_session": {"decomposition": {"materialization_allowed": False}},
                        }
                    )
                ),
                "[req_1] 拆解方案尚未允许生成执行任务，请先补充缺失信息并重新拆解。",
            ),
        ]

        for raw_args, host, expected in cases:
            with self.subTest(raw_args=raw_args):
                self.assertEqual(delivery_command_executor.command_coding_materialize(host, raw_args), expected)
                self.assertFalse(host.start_run_called)
                self.assertFalse(host.implement_called)

    def test_materialize_approved_breakdown_binds_ledger_callbacks_and_formats_children(self):
        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {
                "decomposition": {
                    "materialization_allowed": True,
                    "delivery_units": [
                        {
                            "unit_id": "unit_backend",
                            "title": "后端订单查询能力",
                            "summary": "支持新增筛选条件",
                        }
                    ],
                }
            },
        }
        ledger = RecordingLedger(task)
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertIn("[req_1] 已生成 1 个执行任务", message)
        self.assertIn("支持新增筛选条件", message)
        self.assertEqual(ledger.list_child_task_ids, ["req_1"])
        self.assertEqual(len(ledger.created_task_ids), 1)
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_materialize_reports_plan_errors_without_partial_children(self):
        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {
                "decomposition": {
                    "materialization_allowed": True,
                    "delivery_units": [
                        {"unit_id": "unit_backend", "title": "后端", "summary": "后端能力"},
                        {"unit_id": "unit_backend", "title": "重复", "summary": "重复能力"},
                    ],
                }
            },
        }
        ledger = RecordingLedger(task)
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertIn("拆解方案不能生成执行任务", message)
        self.assertIn("delivery_units[1].unit_id duplicates unit_backend", message)
        self.assertEqual(ledger.created_task_ids, [])
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_materialize_returns_existing_children_without_recreating(self):
        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {"decomposition": {"materialization_allowed": True}},
        }
        ledger = RecordingLedger(task)
        ledger.children["task_existing"] = {
            "task_id": "task_existing",
            "requirement_summary": "已存在的执行任务",
        }
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertIn("[req_1] 已生成 1 个执行任务", message)
        self.assertIn("- task_existing：已存在的执行任务", message)
        self.assertEqual(ledger.created_task_ids, [])
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_materialize_reports_empty_children_from_delivery_service(self):
        class EmptyDeliveryService:
            def materialize_execution_tasks(self, *args: Any, **kwargs: Any):
                return type("Result", (), {"children": [], "errors": []})()

        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {"decomposition": {"materialization_allowed": True}},
        }
        host = RecordingHost(RecordingLedger(task))
        host.delivery_service = EmptyDeliveryService()

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertEqual(message, "[req_1] 拆解方案里没有可生成的执行任务，请重新拆解。")
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)


if __name__ == "__main__":
    unittest.main()
