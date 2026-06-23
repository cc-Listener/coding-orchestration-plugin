from __future__ import annotations

import unittest
from unittest import mock

from coding_orchestration.gateway import gateway_command_controller as controller
from coding_orchestration.gateway import gateway_command_executor as executor
from coding_orchestration import merge_test_presenter
from coding_orchestration import run_start_presenter
from coding_orchestration.models import TaskPhase, TaskStatus


class FakeLedger:
    def __init__(self, task=None):
        self.task = task
        self.phase_updates = []
        self.merge_records = []

    def get_task(self, task_id):
        if self.task and self.task.get("task_id") == task_id:
            return dict(self.task)
        return None

    def update_phase(self, task_id, phase):
        self.phase_updates.append((task_id, phase))
        if self.task and self.task.get("task_id") == task_id:
            self.task["phase"] = phase

    def append_merge_record(self, task_id, record):
        self.merge_records.append((task_id, record))


class FakeHost:
    def __init__(self):
        self.active_task_id = "task_active"
        self.messages = []
        self.background_plan_started = []
        self.background_merge_started = []
        self.pending_actions = []
        self.assessment = {}
        self.release = {}
        self.blocker = ""
        self.qa_evidence = {"status": "ok"}
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

    def _start_background_merge_test(self, task_id, gateway, event):
        self.background_merge_started.append(task_id)

    def command_coding_breakdown(self, task_id):
        return f"breakdown: {task_id}"

    def _active_task_id_for_event(self, event):
        return self.active_task_id

    def _blocked_task_merge_test_assessment(self, task):
        return dict(self.assessment)

    def _store_pending_action_for_event(self, event, **pending):
        self.pending_actions.append(pending)

    def _release_blocked_task_for_merge_test_if_allowed(self, task, *, accept_risk=False):
        return dict(self.release) if accept_risk else {}

    def _merge_test_blocker(self, task):
        return self.blocker

    def _qa_evidence_for_merge_test(self, task):
        return dict(self.qa_evidence)

    def _event_source_for_ledger(self, event):
        return "gateway:event"


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

    def test_merge_test_risk_confirmation_uses_presenter_and_pending_action(self):
        host = FakeHost()
        host.ledger = FakeLedger({"task_id": "task_active", "status": TaskStatus.BLOCKED.value})
        host.assessment = {"requires_acceptance": True, "impact": "只跑了定点测试"}
        route = controller.route_coding_gateway_command("/coding merge-test task_active")

        with mock.patch.object(
            merge_test_presenter,
            "blocked_merge_test_risk_confirmation_message",
            side_effect=lambda task_id, assessment: f"risk: {task_id}: {assessment.get('impact')}",
        ) as presenter:
            result = executor.handle_gateway_custom_route(
                host,
                route,
                text="/coding merge-test task_active",
                event=object(),
                gateway=object(),
            )

        self.assertEqual(result, executor.HANDLED_BY_CODING_ORCHESTRATION)
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.messages, ["risk: task_active: 只跑了定点测试"])
        self.assertEqual(host.pending_actions[0]["action"], "merge_test_accept_risk")
        self.assertEqual(host.background_merge_started, [])

    def test_merge_test_qa_risk_uses_presenter_and_pending_action(self):
        host = FakeHost()
        host.ledger = FakeLedger({"task_id": "task_active", "status": TaskStatus.READY_FOR_MERGE_TEST.value})
        host.qa_evidence = {"requires_confirmation": "true", "impact": "缺少可信 QA 通过证据"}
        route = controller.route_coding_gateway_command("/coding merge-test task_active")

        with mock.patch.object(
            merge_test_presenter,
            "merge_test_qa_risk_confirmation_message",
            side_effect=lambda task_id, qa_evidence: f"qa-risk: {task_id}: {qa_evidence.get('impact')}",
        ) as presenter:
            result = executor.handle_gateway_custom_route(
                host,
                route,
                text="/coding merge-test task_active",
                event=object(),
                gateway=object(),
            )

        self.assertEqual(result, executor.HANDLED_BY_CODING_ORCHESTRATION)
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.messages, ["qa-risk: task_active: 缺少可信 QA 通过证据"])
        self.assertEqual(host.pending_actions[0]["action"], "merge_test_qa_risk")
        self.assertEqual(host.background_merge_started, [])

    def test_merge_test_start_uses_presenter_release_note_and_background_run(self):
        host = FakeHost()
        host.ledger = FakeLedger(
            {
                "task_id": "task_active",
                "status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "task_session": {"source_branch": "codex/task-active"},
            }
        )
        host.release = {"accepted_risk": True, "impact": "缺少全量验证"}
        route = controller.route_coding_gateway_command("/coding merge-test task_active --accept-risk")

        with (
            mock.patch.object(
                merge_test_presenter,
                "merge_test_started_message",
                side_effect=lambda task: f"started: {task['task_id']}",
            ) as started_presenter,
            mock.patch.object(
                merge_test_presenter,
                "blocked_merge_test_release_note",
                side_effect=lambda release: f"release: {release.get('impact')}",
            ) as release_presenter,
        ):
            result = executor.handle_gateway_custom_route(
                host,
                route,
                text="/coding merge-test task_active --accept-risk",
                event=object(),
                gateway=object(),
            )

        self.assertEqual(result, executor.HANDLED_BY_CODING_ORCHESTRATION)
        self.assertEqual(started_presenter.call_count, 1)
        self.assertEqual(release_presenter.call_count, 1)
        self.assertEqual(host.messages, ["started: task_active\nrelease: 缺少全量验证"])
        self.assertEqual(host.ledger.phase_updates, [("task_active", TaskPhase.READY_TO_MERGE_TEST.value)])
        self.assertEqual(host.ledger.merge_records[-1][1]["type"], "merge_test_requested")
        self.assertEqual(host.background_merge_started, ["task_active"])


if __name__ == "__main__":
    unittest.main()
