from __future__ import annotations

import unittest

from coding_orchestration import gateway_pending_action_executor as executor
from coding_orchestration import gateway_command_controller
from coding_orchestration.models import RunMode, TaskStatus


class FakeLedger:
    def __init__(self, tasks=None):
        self.tasks = tasks or {}

    def get_task(self, task_id):
        task = self.tasks.get(task_id)
        return dict(task) if task else None


class FakeHost:
    def __init__(self):
        self.pending = None
        self.latest_task = None
        self.latest_report = {}
        self.qa_evidence = {}
        self.messages = []
        self.cleared = 0
        self.confirmations = []
        self.explicit_commands = []
        self.explicit_result = {"action": "skip", "reason": "handled_by_coding_orchestration"}
        self.ledger = FakeLedger({"task_1": {"task_id": "task_1", "status": TaskStatus.READY_FOR_MERGE_TEST.value}})

    def _pending_action_for_event(self, event):
        return self.pending

    def _is_human_confirmation_reply(self, text):
        return gateway_command_controller.is_human_confirmation_reply(text)

    def _is_human_cancellation_reply(self, text):
        return gateway_command_controller.is_human_cancellation_reply(text)

    def _clear_pending_action_for_event(self, event):
        self.cleared += 1
        self.pending = None
        return True

    def _reply_if_possible(self, gateway, event, message):
        self.messages.append(message)

    def _task_is_cancelled(self, task):
        return task.get("status") == TaskStatus.CANCELLED.value

    def _cancelled_task_message(self, task):
        return f"cancelled: {task['task_id']}"

    def _record_pending_action_confirmation(self, pending, text, event):
        self.confirmations.append((pending, text))

    def _handle_explicit_gateway_command(self, command_text, event, gateway):
        self.explicit_commands.append(command_text)
        return self.explicit_result

    def _active_task_for_event(self, event):
        return self.latest_task

    def _read_report_json(self, path):
        return dict(self.latest_report)

    def _qa_evidence_for_merge_test(self, task):
        return dict(self.qa_evidence)


class GatewayPendingActionExecutorTest(unittest.TestCase):
    def test_confirmed_binding_clears_records_and_dispatches_command(self):
        host = FakeHost()
        host.pending = {
            "task_id": "task_1",
            "action": "merge_test_retry",
            "command_text": "/coding merge-test task_1",
            "reason": "等待确认",
        }

        result = executor.handle_pending_action_gateway_message(
            host,
            "确认",
            event=object(),
            gateway=object(),
            include_latest_human_required=False,
        )

        self.assertEqual(result, {"action": "skip", "reason": "coding_pending_action_confirmed"})
        self.assertEqual(host.cleared, 1)
        self.assertEqual(host.confirmations[0][1], "确认")
        self.assertEqual(host.explicit_commands, ["/coding merge-test task_1"])

    def test_cancellation_clears_binding_and_replies(self):
        host = FakeHost()
        host.pending = {"task_id": "task_1", "command_text": "/coding merge-test task_1"}

        result = executor.handle_pending_action_gateway_message(
            host,
            "取消",
            event=object(),
            gateway=object(),
            include_latest_human_required=False,
        )

        self.assertEqual(result, {"action": "skip", "reason": "coding_pending_action_cancelled"})
        self.assertEqual(host.cleared, 1)
        self.assertEqual(host.messages, ["已取消当前待确认动作，未启动新的执行。"])

    def test_latest_human_required_run_becomes_pending_command_when_included(self):
        host = FakeHost()
        host.latest_task = {
            "task_id": "task_1",
            "agent_runs": [
                {
                    "run_id": "run_wait",
                    "mode": RunMode.MERGE_TEST.value,
                    "artifact": {"report": "/tmp/report.json"},
                }
            ],
        }
        host.latest_report = {"human_required": True, "summary_markdown": "需要确认未跟踪文件"}
        host.qa_evidence = {"requires_confirmation": "true"}

        pending = executor.pending_action_from_latest_human_required_run(host, object())

        self.assertEqual(pending["task_id"], "task_1")
        self.assertEqual(pending["action"], "merge_test_retry")
        self.assertEqual(pending["command_text"], "/coding merge-test task_1 --confirm-qa-risk")
        self.assertEqual(pending["run_id"], "run_wait")

    def test_invalid_confirmed_action_replies_with_expired_candidate(self):
        host = FakeHost()
        host.explicit_result = None
        host.pending = {
            "task_id": "task_1",
            "action": "merge_test_retry",
            "command_text": "/coding merge-test task_1",
            "reason": "等待确认",
        }

        result = executor.handle_pending_action_gateway_message(
            host,
            "确定",
            event=object(),
            gateway=object(),
            include_latest_human_required=False,
        )

        self.assertEqual(result, {"action": "skip", "reason": "coding_pending_action_confirmed"})
        self.assertIn("待确认动作已失效", host.messages[-1])


if __name__ == "__main__":
    unittest.main()
