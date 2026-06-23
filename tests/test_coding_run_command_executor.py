import unittest
from unittest import mock

from coding_orchestration.coding_commands import coding_run_command_executor
from coding_orchestration import run_start_presenter
from coding_orchestration.models import RunMode, TaskPhase


class FakeLedger:
    def __init__(self, tasks):
        self.tasks = dict(tasks)
        self.human_decisions = []
        self.phase_updates = []

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def append_human_decision(self, task_id, decision):
        self.human_decisions.append((task_id, decision))

    def update_phase(self, task_id, phase):
        self.phase_updates.append((task_id, phase))


class FakeHost:
    def __init__(self, tasks):
        self.ledger = FakeLedger(tasks)
        self.start_calls = []
        self.qa_requests = []
        self.start_error = None
        self.qa_blocker = None

    def start_run(self, task_id, *, mode):
        self.start_calls.append((task_id, mode))
        if self.start_error is not None:
            raise self.start_error
        return {"status": "success", "mode": mode.value}

    def _task_is_cancelled(self, task):
        return task.get("status") == "cancelled"

    def _cancelled_task_message(self, task):
        return f"cancelled:{task['task_id']}"

    def _task_is_plan_ready_for_implementation(self, task):
        return task.get("status") == "planned"

    def _qa_start_blocker(self, task):
        return self.qa_blocker

    def _record_qa_request(self, task_id, text, event):
        self.qa_requests.append((task_id, text, event))


class CodingRunCommandExecutorTest(unittest.TestCase):
    def test_command_run_requires_existing_task_and_starts_plan_only(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": "planned"}})

        self.assertEqual(coding_run_command_executor.command_coding_run(host, ""), "请提供任务 ID。")
        self.assertEqual(coding_run_command_executor.command_coding_run(host, "missing"), "未找到任务：missing")
        with mock.patch.object(
            coding_run_command_executor.run_completion_presenter,
            "format_run_completion_message",
            side_effect=lambda task_id, result: f"run-complete:{task_id}:{result['mode']}",
        ) as presenter:
            message = coding_run_command_executor.command_coding_run(host, "task_1")

        self.assertEqual(message, "run-complete:task_1:plan-only")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.start_calls, [("task_1", RunMode.PLAN_ONLY)])

    def test_command_run_returns_start_run_error(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": "planned"}})
        host.start_error = ValueError("already running")

        message = coding_run_command_executor.command_coding_run(host, "task_1")

        self.assertEqual(message, "already running")
        self.assertEqual(host.start_calls, [("task_1", RunMode.PLAN_ONLY)])

    def test_command_implement_records_decision_before_plan_ready(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": "needs_human"}})

        with mock.patch.object(
            run_start_presenter,
            "implementation_blocked_before_plan_ready_message",
            side_effect=lambda task: f"not-plan-ready:{task['task_id']}",
        ) as presenter:
            message = coding_run_command_executor.command_coding_implement(host, "task_1")

        self.assertEqual(message, "not-plan-ready:task_1")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.start_calls, [])
        self.assertEqual(host.ledger.human_decisions[0][0], "task_1")
        self.assertEqual(host.ledger.human_decisions[0][1]["type"], "implementation_command_before_plan_ready")

    def test_command_implement_starts_implementation_when_plan_ready(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": "planned"}})

        with mock.patch.object(
            coding_run_command_executor.run_completion_presenter,
            "format_implementation_completion_message",
            side_effect=lambda task_id, result: f"implementation-complete:{task_id}:{result['mode']}",
        ) as presenter:
            message = coding_run_command_executor.command_coding_implement(host, "task_1")

        self.assertEqual(message, "implementation-complete:task_1:implementation")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.ledger.phase_updates, [("task_1", TaskPhase.PLAN_APPROVED.value)])
        self.assertEqual(host.start_calls, [("task_1", RunMode.IMPLEMENTATION)])

    def test_command_implement_rejects_cancelled_task(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": "cancelled"}})

        message = coding_run_command_executor.command_coding_implement(host, "task_1")

        self.assertEqual(message, "cancelled:task_1")
        self.assertEqual(host.start_calls, [])

    def test_command_qa_records_request_after_blocker_check(self):
        host = FakeHost({"task_1": {"task_id": "task_1", "status": "ready_for_merge_test"}})
        host.qa_blocker = "qa blocked"

        self.assertEqual(coding_run_command_executor.command_coding_qa(host, "task_1"), "qa blocked")
        self.assertEqual(host.qa_requests, [])

        host.qa_blocker = None
        with mock.patch.object(
            coding_run_command_executor.run_completion_presenter,
            "format_qa_completion_message",
            side_effect=lambda task_id, result: f"qa-complete:{task_id}:{result['mode']}",
        ) as presenter:
            message = coding_run_command_executor.command_coding_qa(host, "task_1")

        self.assertEqual(message, "qa-complete:task_1:qa")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.qa_requests, [("task_1", "/coding qa task_1", None)])
        self.assertEqual(host.start_calls, [("task_1", RunMode.QA)])


if __name__ == "__main__":
    unittest.main()
