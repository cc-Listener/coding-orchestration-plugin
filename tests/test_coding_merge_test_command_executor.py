from __future__ import annotations

import unittest

from coding_orchestration import coding_merge_test_command_executor
from coding_orchestration.models import RunMode, TaskPhase, TaskStatus


class FakeLedger:
    def __init__(self, task: dict):
        self.task = task
        self.phase_updates: list[tuple[str, str]] = []

    def get_task(self, task_id: str) -> dict | None:
        return self.task if task_id == self.task.get("task_id") else None

    def update_phase(self, task_id: str, phase: str) -> None:
        self.phase_updates.append((task_id, phase))
        self.task["phase"] = phase

    def append_merge_record(self, task_id: str, record: dict) -> None:
        self.task.setdefault("merge_records", []).append(record)


class FakeHost:
    def __init__(self, task: dict):
        self.ledger = FakeLedger(task)
        self.assessment: dict = {}
        self.release: dict = {}
        self.blocker = ""
        self.qa_evidence: dict[str, str] = {"status": "missing", "message": "未发现 QA 证据"}
        self.transitions: list[tuple[str, TaskStatus, TaskPhase, str]] = []
        self.start_calls: list[tuple[str, RunMode]] = []

    @staticmethod
    def _task_is_cancelled(task: dict) -> bool:
        return str(task.get("status") or "") == TaskStatus.CANCELLED.value

    @staticmethod
    def _cancelled_task_message(task: dict) -> str:
        return f"任务已取消：{task.get('task_id')}"

    def _blocked_task_merge_test_assessment(self, task: dict) -> dict:
        return dict(self.assessment)

    @staticmethod
    def _blocked_merge_test_risk_confirmation_message(task_id: str, assessment: dict) -> str:
        return f"风险确认 {task_id}: {assessment.get('reason') or ''} --accept-risk"

    @staticmethod
    def _merge_test_qa_risk_confirmation_message(
        task_id: str,
        qa_evidence: dict[str, str],
        *,
        include_reply_hint: bool = True,
    ) -> str:
        return f"QA 风险 {task_id}: {qa_evidence.get('status')} --confirm-qa-risk"

    def _transition_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        phase: TaskPhase,
        reason: str,
    ) -> None:
        self.transitions.append((task_id, status, phase, reason))
        self.ledger.task["status"] = status.value
        self.ledger.task["phase"] = phase.value

    def _merge_test_blocker(self, task: dict) -> str:
        return self.blocker

    def _release_blocked_task_for_merge_test_if_allowed(self, task: dict, *, accept_risk: bool = False) -> dict:
        return dict(self.release) if accept_risk else {}

    def _qa_evidence_for_merge_test(self, task: dict) -> dict[str, str]:
        return dict(self.qa_evidence)

    def start_run(self, task_id: str, *, mode: RunMode) -> dict:
        self.start_calls.append((task_id, mode))
        return {"status": "success"}

    @staticmethod
    def _format_merge_test_completion_message(task_id: str, result: dict) -> str:
        return f"merge-test 已处理：{task_id}"

    @staticmethod
    def _blocked_merge_test_release_note(release: dict) -> str:
        return f"已按风险确认继续：{release.get('reason')}"


class CodingMergeTestCommandExecutorTest(unittest.TestCase):
    def test_prepare_merge_test_marks_ready_task_and_records_preparation(self):
        host = FakeHost(
            {
                "task_id": "task_1",
                "status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "phase": TaskPhase.PLAN_APPROVED.value,
            }
        )

        message = coding_merge_test_command_executor.command_prepare_merge_test(host, "task_1")

        self.assertIn("/coding merge-test task_1", message)
        self.assertEqual(host.ledger.task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
        self.assertEqual(host.ledger.task["merge_records"][-1]["type"], "merge_test_prepared")
        self.assertFalse(host.ledger.task["merge_records"][-1]["known_gaps"])

    def test_prepare_merge_test_returns_risk_confirmation_for_blocked_task(self):
        host = FakeHost({"task_id": "task_1", "status": TaskStatus.BLOCKED.value})
        host.assessment = {"mergeable": True, "requires_acceptance": True, "reason": "missing_report"}

        message = coding_merge_test_command_executor.command_prepare_merge_test(host, "task_1")

        self.assertIn("风险确认 task_1", message)
        self.assertIn("--accept-risk", message)
        self.assertEqual(host.ledger.task.get("merge_records"), None)

    def test_merge_test_requires_qa_confirmation_before_starting_run(self):
        host = FakeHost({"task_id": "task_1", "status": TaskStatus.READY_FOR_MERGE_TEST.value})
        host.qa_evidence = {
            "requires_confirmation": "true",
            "status": "failed",
            "impact": "核心流程失败",
            "recovery_action": "重新 QA",
        }

        message = coding_merge_test_command_executor.command_coding_merge_test(host, "task_1")

        self.assertIn("--confirm-qa-risk", message)
        self.assertEqual(host.start_calls, [])

    def test_merge_test_records_request_and_starts_merge_run(self):
        host = FakeHost({"task_id": "task_1", "status": TaskStatus.READY_FOR_MERGE_TEST.value})

        message = coding_merge_test_command_executor.command_coding_merge_test(host, "task_1 --confirm-qa-risk")

        self.assertIn("merge-test 已处理：task_1", message)
        self.assertEqual(host.ledger.task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
        self.assertEqual(host.ledger.task["merge_records"][-1]["type"], "merge_test_requested")
        self.assertEqual(host.start_calls, [("task_1", RunMode.MERGE_TEST)])


if __name__ == "__main__":
    unittest.main()
