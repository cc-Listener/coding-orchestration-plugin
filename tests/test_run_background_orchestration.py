import unittest

from coding_orchestration import run_background_orchestration
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus


class FakeLedger:
    def __init__(self, tasks=None):
        self.tasks = tasks or {}
        self.decisions = []

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def append_human_decision(self, task_id, decision):
        self.decisions.append((task_id, decision))


class FakeHost:
    def __init__(self):
        self.ledger = FakeLedger()
        self.reconciled = None
        self.transitions = []
        self.reports = {}
        self.qa_evidence = {}
        self.pending_actions = []

    def _timeout_seconds_for_mode(self, mode):
        return 1

    def _reconcile_completed_active_run(self, task_id, *, task=None):
        return self.reconciled

    def _transition_task_status(self, task_id, status, *, phase=None, reason=""):
        self.transitions.append((task_id, status, phase, reason))

    def _read_report_json(self, path):
        return self.reports.get(path, {})

    def _qa_evidence_for_merge_test(self, task):
        return self.qa_evidence

    def _store_pending_action_for_event(self, event, **payload):
        self.pending_actions.append((event, payload))
        return True


class RunBackgroundOrchestrationTest(unittest.TestCase):
    def test_wait_for_background_run_completion_returns_reconciled_result(self):
        host = FakeHost()
        host.ledger.tasks["task_1"] = {
            "task_id": "task_1",
            "task_session": {"runner": {"active_run_id": "run_1"}},
        }
        host.reconciled = {"run_id": "run_1", "status": AgentRunStatus.SUCCESS.value}

        result = run_background_orchestration.wait_for_background_run_completion(
            host,
            "task_1",
            {"run_id": "run_1", "status": AgentRunStatus.QUEUED.value},
            mode=RunMode.PLAN_ONLY,
        )

        self.assertEqual(result, host.reconciled)

    def test_wait_for_background_run_completion_returns_original_for_stale_active_run(self):
        host = FakeHost()
        original = {"run_id": "run_old", "status": AgentRunStatus.RUNNING.value}
        host.ledger.tasks["task_1"] = {
            "task_id": "task_1",
            "task_session": {"runner": {"active_run_id": "run_new"}},
        }

        result = run_background_orchestration.wait_for_background_run_completion(
            host,
            "task_1",
            original,
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertIs(result, original)

    def test_mark_background_run_failed_transitions_non_terminal_task(self):
        host = FakeHost()
        host.ledger.tasks["task_1"] = {"task_id": "task_1", "status": TaskStatus.PLANNED.value}

        run_background_orchestration.mark_background_run_failed(
            host,
            "task_1",
            RuntimeError("runner unavailable"),
            mode=RunMode.QA,
        )

        self.assertEqual(host.transitions[0][0], "task_1")
        self.assertEqual(host.transitions[0][1], TaskStatus.FAILED)
        self.assertEqual(host.transitions[0][2], TaskPhase.RUNNER_FAILED)
        self.assertIn("qa startup failed: runner unavailable", host.transitions[0][3])

    def test_mark_background_run_failed_does_not_override_done_task(self):
        host = FakeHost()
        host.ledger.tasks["task_done"] = {"task_id": "task_done", "status": TaskStatus.DONE.value}

        run_background_orchestration.mark_background_run_failed(
            host,
            "task_done",
            RuntimeError("late failure"),
            mode=RunMode.MERGE_TEST,
        )

        self.assertEqual(host.transitions, [])

    def test_mark_background_run_failed_records_rejected_transition(self):
        class RejectingHost(FakeHost):
            def _transition_task_status(self, task_id, status, *, phase=None, reason=""):
                raise ValueError("invalid transition")

        host = RejectingHost()
        host.ledger.tasks["task_1"] = {"task_id": "task_1", "status": TaskStatus.PLANNED.value}

        run_background_orchestration.mark_background_run_failed(
            host,
            "task_1",
            RuntimeError("runner unavailable"),
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertEqual(host.ledger.decisions[0][0], "task_1")
        self.assertEqual(host.ledger.decisions[0][1]["type"], "background_failure_transition_rejected")
        self.assertEqual(host.ledger.decisions[0][1]["transition_error"], "invalid transition")

    def test_store_pending_action_from_merge_test_result_ignores_non_human_required_report(self):
        host = FakeHost()
        host.reports["report.json"] = {"human_required": False}

        stored = run_background_orchestration.store_pending_action_from_merge_test_result(
            host,
            object(),
            "task_1",
            {"run_id": "run_1", "artifacts": {"report": "report.json"}},
        )

        self.assertFalse(stored)
        self.assertEqual(host.pending_actions, [])

    def test_store_pending_action_from_merge_test_result_preserves_qa_risk_flag(self):
        host = FakeHost()
        event = object()
        host.ledger.tasks["task_1"] = {"task_id": "task_1"}
        host.reports["report.json"] = {
            "human_required": True,
            "summary_markdown": "需要确认 QA 风险",
        }
        host.qa_evidence = {"requires_confirmation": "true"}

        stored = run_background_orchestration.store_pending_action_from_merge_test_result(
            host,
            event,
            "task_1",
            {"run_id": "run_1", "artifacts": {"report": "report.json"}},
        )

        self.assertTrue(stored)
        self.assertEqual(host.pending_actions[0][0], event)
        self.assertEqual(host.pending_actions[0][1]["action"], "merge_test_retry")
        self.assertEqual(host.pending_actions[0][1]["command_text"], "/coding merge-test task_1 --confirm-qa-risk")
        self.assertEqual(host.pending_actions[0][1]["reason"], "需要确认 QA 风险")
        self.assertEqual(host.pending_actions[0][1]["run_id"], "run_1")


if __name__ == "__main__":
    unittest.main()
