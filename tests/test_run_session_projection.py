import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.run_session_projection import (
    build_active_run_session_update,
    build_completion_session_update,
    build_plan_report_session_fields,
    build_plan_report_session_update,
    build_run_start_base_session_update,
    build_run_start_workspace_session_update,
    build_runner_session_update,
)


class RunSessionProjectionTest(unittest.TestCase):
    def test_session_projection_lives_in_dedicated_module_with_compatibility_export(self):
        self.assertIs(
            run_orchestration_service.build_plan_report_session_fields,
            build_plan_report_session_fields,
        )
        self.assertIs(
            run_orchestration_service.build_plan_report_session_update,
            build_plan_report_session_update,
        )
        self.assertIs(
            run_orchestration_service.build_completion_session_update,
            build_completion_session_update,
        )
        self.assertIs(
            run_orchestration_service.build_runner_session_update,
            build_runner_session_update,
        )
        self.assertIs(
            run_orchestration_service.build_run_start_base_session_update,
            build_run_start_base_session_update,
        )
        self.assertIs(
            run_orchestration_service.build_run_start_workspace_session_update,
            build_run_start_workspace_session_update,
        )
        self.assertIs(
            run_orchestration_service.build_active_run_session_update,
            build_active_run_session_update,
        )

    def test_run_start_session_projection_records_base_workspace_and_active_run_payloads(self):
        self.assertEqual(
            build_run_start_base_session_update(
                project_name="oms",
                runner_name="codex_cli",
                mode=RunMode.IMPLEMENTATION,
            ),
            {
                "project_name": "oms",
                "runner": {
                    "provider": "codex_cli",
                    "last_requested_mode": RunMode.IMPLEMENTATION.value,
                },
            },
        )

        self.assertEqual(
            build_run_start_workspace_session_update(
                mode=RunMode.IMPLEMENTATION,
                source_branch="codex/task-123",
                source_base_branch="main",
                workspace_path="/tmp/worktree",
            ),
            {
                "source_branch": "codex/task-123",
                "source_base_branch": "main",
                "worktree_path": "/tmp/worktree",
            },
        )
        self.assertEqual(
            build_run_start_workspace_session_update(
                mode=RunMode.QA,
                source_branch="codex/task-123",
                source_base_branch="main",
                workspace_path="/tmp/worktree",
                resume_session_id="session_1",
            )["runner"],
            {"resume_session_id": "session_1"},
        )
        self.assertEqual(
            build_run_start_workspace_session_update(
                mode=RunMode.PLAN_ONLY,
                source_branch="",
                source_base_branch="main",
                workspace_path="/tmp/worktree",
            ),
            {},
        )
        self.assertEqual(
            build_active_run_session_update(
                run_id="run_1",
                mode=RunMode.QA,
            ),
            {"runner": {"active_run_id": "run_1", "active_mode": RunMode.QA.value}},
        )

    def test_completion_session_projection_combines_plan_report_and_runner_contract(self):
        update = build_completion_session_update(
            mode=RunMode.PLAN_ONLY,
            report={
                "branch_slug_candidate": "fix-order-status",
                "execution_policy_decision": {"route": "standard_change"},
                "user_facing_summary": "用户可读计划",
                "technical_summary": "技术计划",
                "next_actions": ["确认计划"],
                "raw_status": "plan_ready",
                "commit_sha": "abc123",
            },
            stale_completion=False,
            runner_name="codex_cli",
            run_id="run_1",
            status=AgentRunStatus.SUCCEEDED.value,
            session_id="thread_1",
            run_still_active=False,
            attach_command="codex resume thread_1",
        )

        self.assertEqual(
            update["plan_report"],
            {
                "branch_slug_candidate": "fix-order-status",
                "execution_policy_decision": {"route": "standard_change"},
                "user_facing_summary": "用户可读计划",
                "technical_summary": "技术计划",
                "next_actions": ["确认计划"],
            },
        )
        self.assertNotIn("commit_sha", update["plan_report"])
        self.assertEqual(update["runner"]["provider"], "codex_cli")
        self.assertEqual(update["runner"]["last_run_id"], "run_1")
        self.assertEqual(update["runner"]["last_run_raw_status"], "plan_ready")
        self.assertEqual(update["runner"]["resume_session_id"], "thread_1")

    def test_completion_session_projection_skips_stale_completion(self):
        self.assertEqual(
            build_completion_session_update(
                mode=RunMode.PLAN_ONLY,
                report={"raw_status": "plan_ready"},
                stale_completion=True,
                runner_name="codex_cli",
                run_id="run_stale",
                status=AgentRunStatus.SUCCEEDED.value,
                session_id="thread_stale",
                run_still_active=False,
                attach_command="codex resume thread_stale",
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
