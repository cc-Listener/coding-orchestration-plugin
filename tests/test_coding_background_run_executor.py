import unittest
from unittest.mock import patch

from coding_orchestration import coding_background_run_executor
from coding_orchestration.models import RunMode


class FakeSource:
    platform = "feishu"
    chat_id = "chat_1"


class FakeEvent:
    source = FakeSource()


class RecordingGateway:
    def __init__(self):
        self.messages = []

    def send_message(self, source, message):
        self.messages.append((source, message))


class FakeHost:
    def __init__(self):
        self.start_calls = []
        self.wait_calls = []
        self.notifications = []
        self.failures = []
        self.pending_actions = []
        self.start_error = None
        self.wait_result = None

    def start_run(self, task_id, *, mode):
        self.start_calls.append((task_id, mode))
        if self.start_error is not None:
            raise self.start_error
        return {"run_id": f"run_{mode.value}", "status": "success", "mode": mode.value}

    def _wait_for_background_run_completion(self, task_id, result, *, mode):
        self.wait_calls.append((task_id, result, mode))
        return self.wait_result or {**result, "task_status": f"{mode.value}_done"}

    def _format_run_completion_message(self, task_id, result):
        return f"plan-message:{task_id}:{result['run_id']}"

    def _format_stale_run_completion_message(self, task_id, result):
        return f"stale-message:{task_id}:{result['run_id']}"

    def _format_implementation_completion_message(self, task_id, result):
        return f"implementation-message:{task_id}:{result['run_id']}"

    def _format_qa_completion_message(self, task_id, result):
        return f"qa-message:{task_id}:{result['run_id']}"

    def _format_merge_test_completion_message(self, task_id, result):
        return f"merge-message:{task_id}:{result['run_id']}"

    def _mark_background_run_failed(self, task_id, exc, *, mode):
        self.failures.append((task_id, str(exc), mode))

    def _record_completion_notification(self, task_id, *, mode, result, reply):
        self.notifications.append((task_id, mode, result, reply))

    def _store_pending_action_from_merge_test_result(self, event, task_id, result):
        self.pending_actions.append((event, task_id, result))
        return True


class CodingBackgroundRunExecutorTest(unittest.TestCase):
    def test_start_background_functions_delegate_with_mode_and_target(self):
        host = FakeHost()
        gateway = RecordingGateway()
        event = FakeEvent()

        with patch.object(coding_background_run_executor.background_run_notifier, "start_background_run") as starter:
            coding_background_run_executor.start_background_plan_only(host, "task_1", gateway, event)
            coding_background_run_executor.start_background_implementation(host, "task_2", gateway, event)
            coding_background_run_executor.start_background_qa(host, "task_3", gateway, event)
            coding_background_run_executor.start_background_merge_test(host, "task_4", gateway, event)

        self.assertEqual(
            [call.kwargs["mode"] for call in starter.call_args_list],
            [RunMode.PLAN_ONLY, RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST],
        )
        self.assertTrue(all(call.kwargs["target"] for call in starter.call_args_list))

    def test_run_plan_only_waits_for_completion_and_records_notification(self):
        host = FakeHost()
        gateway = RecordingGateway()

        coding_background_run_executor.run_plan_only_and_notify(host, "task_1", gateway, FakeEvent(), None)

        self.assertEqual(host.start_calls, [("task_1", RunMode.PLAN_ONLY)])
        self.assertEqual(host.wait_calls[0][2], RunMode.PLAN_ONLY)
        self.assertEqual(gateway.messages[0][1], "plan-message:task_1:run_plan-only")
        self.assertEqual(host.notifications[0][1], RunMode.PLAN_ONLY)
        self.assertEqual(host.notifications[0][3]["status"], "ok")

    def test_run_implementation_uses_stale_completion_message_when_result_is_stale(self):
        host = FakeHost()
        host.wait_result = {
            "run_id": "run_stale",
            "status": "success",
            "mode": RunMode.IMPLEMENTATION.value,
            "stale_completion": True,
        }
        gateway = RecordingGateway()

        coding_background_run_executor.run_implementation_and_notify(host, "task_1", gateway, FakeEvent(), None)

        self.assertEqual(host.start_calls, [("task_1", RunMode.IMPLEMENTATION)])
        self.assertEqual(gateway.messages[0][1], "stale-message:task_1:run_stale")

    def test_run_qa_uses_qa_completion_message(self):
        host = FakeHost()
        gateway = RecordingGateway()

        coding_background_run_executor.run_qa_and_notify(host, "task_1", gateway, FakeEvent(), None)

        self.assertEqual(host.start_calls, [("task_1", RunMode.QA)])
        self.assertEqual(gateway.messages[0][1], "qa-message:task_1:run_qa")

    def test_run_merge_test_stores_pending_action_before_notification(self):
        host = FakeHost()
        event = FakeEvent()
        gateway = RecordingGateway()

        coding_background_run_executor.run_merge_test_and_notify(host, "task_1", gateway, event, None)

        self.assertEqual(host.start_calls, [("task_1", RunMode.MERGE_TEST)])
        self.assertEqual(host.pending_actions[0][0], event)
        self.assertEqual(host.pending_actions[0][1], "task_1")
        self.assertEqual(gateway.messages[0][1], "merge-message:task_1:run_merge-test")

    def test_run_failure_marks_failed_and_records_empty_notification(self):
        host = FakeHost()
        host.start_error = RuntimeError("runner unavailable")
        gateway = RecordingGateway()

        coding_background_run_executor.run_plan_only_and_notify(host, "task_1", gateway, FakeEvent(), None)

        self.assertEqual(host.failures, [("task_1", "runner unavailable", RunMode.PLAN_ONLY)])
        self.assertEqual(host.notifications[0][2], {})
        self.assertIn("[task_1] 计划执行失败：runner unavailable", gateway.messages[0][1])


if __name__ == "__main__":
    unittest.main()
