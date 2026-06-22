from __future__ import annotations

import unittest
from unittest import mock

from coding_orchestration import gateway_command_controller as controller
from coding_orchestration import gateway_command_executor as executor
from coding_orchestration import run_start_presenter
from coding_orchestration.models import TaskStatus


class FakeLedger:
    def __init__(self, task=None):
        self.task = task

    def get_task(self, task_id):
        if self.task and self.task.get("task_id") == task_id:
            return dict(self.task)
        return None


class FakeHost:
    def __init__(self):
        self.active_task_id = "task_active"
        self.messages = []
        self.background_plan_started = []
        self.ledger = FakeLedger({"task_id": "task_active", "status": TaskStatus.PLANNED.value})

    def _reply_if_possible(self, gateway, event, message):
        self.messages.append(message)

    def _gateway_command_task_id(self, route, event):
        return controller.gateway_route_task_id(route, self.active_task_id)

    def _task_is_cancelled(self, task):
        return False

    def _apply_active_project_to_task_if_missing(self, task, event):
        return task

    def _cancelled_task_message(self, task):
        return f"cancelled: {task['task_id']}"

    def _start_background_plan_only(self, task_id, gateway, event):
        self.background_plan_started.append(task_id)

    def command_coding_breakdown(self, task_id):
        return f"breakdown: {task_id}"


class GatewayCommandExecutorTest(unittest.TestCase):
    def test_immediate_route_is_left_to_orchestrator_immediate_dispatch(self):
        host = FakeHost()
        route = controller.route_coding_gateway_command("/coding list")

        result = executor.handle_gateway_custom_route(host, route, text="/coding list", event=object(), gateway=object())

        self.assertIsNone(result)
        self.assertEqual(host.messages, [])

    def test_custom_plan_run_uses_route_task_id_fallback_and_starts_background_run(self):
        host = FakeHost()
        route = controller.route_coding_gateway_command("/coding run")

        with mock.patch.object(
            run_start_presenter,
            "plan_only_started_message",
            side_effect=lambda task: f"plan started: {task['task_id']}",
        ) as presenter:
            result = executor.handle_gateway_custom_route(host, route, text="/coding run", event=object(), gateway=object())

        self.assertEqual(result, executor.HANDLED_BY_CODING_ORCHESTRATION)
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.messages, ["plan started: task_active"])
        self.assertEqual(host.background_plan_started, ["task_active"])

    def test_custom_plan_run_uses_start_presenter_when_task_is_already_running(self):
        host = FakeHost()
        host.ledger = FakeLedger({"task_id": "task_active", "status": TaskStatus.RUNNING.value})
        route = controller.route_coding_gateway_command("/coding run")

        with mock.patch.object(
            run_start_presenter,
            "plan_only_already_running_message",
            side_effect=lambda task: f"already running: {task['task_id']}",
        ) as presenter:
            result = executor.handle_gateway_custom_route(host, route, text="/coding run", event=object(), gateway=object())

        self.assertEqual(result, executor.HANDLED_BY_CODING_ORCHESTRATION)
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.messages, ["already running: task_active"])
        self.assertEqual(host.background_plan_started, [])

    def test_delivery_route_uses_handler_key_and_active_task_fallback(self):
        host = FakeHost()
        route = controller.route_coding_gateway_command("/coding breakdown")

        result = executor.handle_gateway_custom_route(
            host,
            route,
            text="/coding breakdown",
            event=object(),
            gateway=object(),
        )

        self.assertEqual(result, executor.HANDLED_BY_CODING_ORCHESTRATION)
        self.assertEqual(host.messages, ["breakdown: task_active"])


if __name__ == "__main__":
    unittest.main()
