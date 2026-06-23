from __future__ import annotations

import unittest

from coding_orchestration.services import merge_test_readiness_service as service
from coding_orchestration.models import AgentRunStatus, RunMode, TaskStatus


class MergeTestReadinessServiceTest(unittest.TestCase):
    def test_missing_implementation_run_blocks_merge_test(self):
        assessment = service.assess_blocked_merge_test(
            task={"task_id": "task_1", "status": TaskStatus.BLOCKED.value},
            implementation_run=None,
            has_merge_test_workspace=True,
            source_branch="codex/task_1",
            resume_session_id="019e-session",
            report={},
        )

        self.assertFalse(assessment["mergeable"])
        self.assertEqual(assessment["reason"], "missing_implementation_run")
        self.assertNotIn("/coding", assessment["recovery_action"])
        self.assertIn("implementation", assessment["recovery_action"])

    def test_codex_ready_report_is_mergeable(self):
        run = {
            "run_id": "run_impl",
            "mode": RunMode.IMPLEMENTATION.value,
            "status": AgentRunStatus.BLOCKED.value,
            "artifact": {"report": "/tmp/report.json"},
            "source_branch": "codex/task_1",
        }

        assessment = service.assess_blocked_merge_test(
            task={"task_id": "task_1", "status": TaskStatus.BLOCKED.value},
            implementation_run=run,
            has_merge_test_workspace=True,
            source_branch="codex/task_1",
            resume_session_id="019e-session",
            report={
                "status": "blocked",
                "implementation_landed": True,
                "commit_sha": "abc123",
                "merge_readiness": {
                    "ready": True,
                    "required_confirmation": True,
                    "risk_note": "只跑了定点测试。",
                    "recovery_action": "人工确认风险后继续。",
                    "fallback_evidence": "summary.md",
                },
            },
        )

        self.assertTrue(assessment["mergeable"])
        self.assertTrue(assessment["requires_acceptance"])
        self.assertEqual(assessment["reason"], "codex_merge_readiness")
        self.assertEqual(assessment["impact"], "只跑了定点测试。")

    def test_diff_guard_violation_takes_precedence_over_report_readiness(self):
        run = {
            "run_id": "run_impl",
            "mode": RunMode.IMPLEMENTATION.value,
            "status": AgentRunStatus.BLOCKED.value,
            "artifact": {"report": "/tmp/report.json"},
            "source_branch": "codex/task_1",
            "diff_guard": {"violations": ["outside path"]},
        }

        assessment = service.assess_blocked_merge_test(
            task={"task_id": "task_1", "status": TaskStatus.BLOCKED.value},
            implementation_run=run,
            has_merge_test_workspace=True,
            source_branch="codex/task_1",
            resume_session_id="019e-session",
            report={
                "status": "blocked",
                "implementation_landed": True,
                "commit_sha": "abc123",
                "merge_readiness": {"ready": True},
            },
        )

        self.assertFalse(assessment["mergeable"])
        self.assertEqual(assessment["reason"], "diff_guard_violation")
        self.assertTrue(assessment["requires_acceptance"])

    def test_not_landed_report_requires_risk_acceptance(self):
        run = {
            "run_id": "run_impl",
            "mode": RunMode.IMPLEMENTATION.value,
            "status": AgentRunStatus.BLOCKED.value,
            "artifact": {"report": "/tmp/report.json"},
            "source_branch": "codex/task_1",
        }

        assessment = service.assess_blocked_merge_test(
            task={"task_id": "task_1", "status": TaskStatus.BLOCKED.value},
            implementation_run=run,
            has_merge_test_workspace=True,
            source_branch="codex/task_1",
            resume_session_id="019e-session",
            report={
                "status": "blocked",
                "implementation_landed": False,
                "commit_sha": "",
                "merge_readiness": {"ready": True},
            },
        )

        self.assertFalse(assessment["mergeable"])
        self.assertEqual(assessment["reason"], "implementation_not_landed")
        self.assertTrue(assessment["requires_acceptance"])


if __name__ == "__main__":
    unittest.main()
