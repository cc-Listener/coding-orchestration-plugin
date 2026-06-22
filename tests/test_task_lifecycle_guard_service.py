import unittest

from coding_orchestration import task_lifecycle_guard_service
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus


class FakeLedger:
    def __init__(self, tasks=None):
        self.tasks = dict(tasks or {})
        self.decisions = []

    def append_human_decision(self, task_id, decision):
        self.decisions.append((task_id, decision))
        task = self.tasks[task_id]
        task.setdefault("human_decisions", []).append(decision)

    def get_task(self, task_id):
        return self.tasks.get(task_id)


class FakeHost:
    def __init__(self, tasks=None):
        self.ledger = FakeLedger(tasks)
        self.transitions = []

    def _run_status_details_from_report(self, run, run_mode, fallback_status=""):
        return {
            "status": fallback_status,
            "structured": run.get("structured", True),
            "status_detail": run.get("status_detail", ""),
        }

    def _run_details_are_runner_failed(self, details):
        return details.get("status") == AgentRunStatus.RUNNER_FAILED.value

    def _transition_task_status(self, task_id, status, *, phase=None, reason=""):
        self.transitions.append((task_id, status, phase, reason))
        task = self.ledger.tasks[task_id]
        task["status"] = status.value if hasattr(status, "value") else status
        task["phase"] = phase.value if hasattr(phase, "value") else phase
        return {"ok": True}

    def _event_source_for_ledger(self, event):
        return {"platform": "feishu", "message_id": getattr(event, "message_id", "")}


class FakeEvent:
    message_id = "msg_1"


class TaskLifecycleGuardServiceTest(unittest.TestCase):
    def test_active_coding_statuses_exclude_terminal_done_and_cancelled(self):
        statuses = task_lifecycle_guard_service.active_coding_statuses()

        self.assertIn(TaskStatus.PLANNED.value, statuses)
        self.assertIn(TaskStatus.MERGED_TEST.value, statuses)
        self.assertNotIn(TaskStatus.DONE.value, statuses)
        self.assertNotIn(TaskStatus.CANCELLED.value, statuses)

    def test_cancelled_task_message_accepts_task_or_task_id(self):
        message = task_lifecycle_guard_service.cancelled_task_message({"task_id": "task_1"})
        id_message = task_lifecycle_guard_service.cancelled_task_message("task_2")

        self.assertIn("[task_1] 已取消，不能继续操作。", message)
        self.assertIn("已取消是人工终态保护", message)
        self.assertIn("[task_2] 已取消，不能继续操作。", id_message)

    def test_restore_state_for_cancelled_task_prefers_successful_merge_test(self):
        host = FakeHost()
        task = {
            "task_id": "task_1",
            "project_path": "/repo/demo",
            "agent_runs": [
                {"mode": RunMode.IMPLEMENTATION.value, "status": AgentRunStatus.BLOCKED.value},
                {"mode": RunMode.MERGE_TEST.value, "status": AgentRunStatus.SUCCEEDED.value},
            ],
        }

        status, phase, reason = task_lifecycle_guard_service.restore_state_for_cancelled_task(host, task)

        self.assertEqual(status, TaskStatus.MERGED_TEST)
        self.assertEqual(phase, TaskPhase.MERGED_TEST)
        self.assertEqual(reason, "最近 merge-test 已成功")

    def test_restore_state_for_cancelled_task_falls_back_to_planned_with_project_context(self):
        host = FakeHost()
        task = {"task_id": "task_1", "project_path": "/repo/demo", "agent_runs": []}

        status, phase, reason = task_lifecycle_guard_service.restore_state_for_cancelled_task(host, task)

        self.assertEqual(status, TaskStatus.PLANNED)
        self.assertEqual(phase, TaskPhase.PLAN_READY)
        self.assertIn("已有项目上下文", reason)

    def test_reopen_merged_test_task_for_bugfix_records_transition_and_decision(self):
        task = {
            "task_id": "task_1",
            "status": TaskStatus.MERGED_TEST.value,
            "phase": TaskPhase.MERGED_TEST.value,
            "human_decisions": [],
        }
        host = FakeHost({"task_1": task})

        reopened = task_lifecycle_guard_service.reopen_merged_test_task_for_bugfix_if_needed(
            host,
            task,
            FakeEvent(),
        )

        self.assertEqual(reopened["status"], TaskStatus.PLANNED.value)
        self.assertEqual(reopened["phase"], TaskPhase.BUGFIXING.value)
        self.assertEqual(
            host.transitions,
            [("task_1", TaskStatus.PLANNED, TaskPhase.BUGFIXING, "bugfix feedback after merged_test")],
        )
        self.assertEqual(host.ledger.decisions[0][0], "task_1")
        self.assertEqual(host.ledger.decisions[0][1]["type"], "merged_test_reopened_for_bugfix")
        self.assertEqual(host.ledger.decisions[0][1]["gateway_source"]["message_id"], "msg_1")


if __name__ == "__main__":
    unittest.main()
