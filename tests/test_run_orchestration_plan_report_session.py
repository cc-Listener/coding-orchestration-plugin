import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import RunMode


class RunOrchestrationPlanReportSessionTest(unittest.TestCase):
    def test_build_plan_report_session_fields_whitelists_only_session_safe_fields(self):
        source_report = {
            "branch_slug_candidate": "fix-order-status",
            "execution_policy_decision": {"route": "standard_change"},
            "user_facing_summary": "用户可读计划",
            "technical_summary": "技术计划",
            "next_actions": ["确认计划", "进入实现"],
            "implementation_landed": False,
            "commit_sha": "abc123",
            "changed_files_summary": ["src/app.py"],
            "merge_readiness": {"ready": False},
        }

        plan_report = run_orchestration_service.build_plan_report_session_fields(source_report)

        self.assertEqual(
            plan_report,
            {
                "branch_slug_candidate": "fix-order-status",
                "execution_policy_decision": {"route": "standard_change"},
                "user_facing_summary": "用户可读计划",
                "technical_summary": "技术计划",
                "next_actions": ["确认计划", "进入实现"],
            },
        )
        self.assertEqual(source_report["commit_sha"], "abc123")
        self.assertNotIn("implementation_landed", plan_report)
        self.assertNotIn("commit_sha", plan_report)
        self.assertNotIn("changed_files_summary", plan_report)
        self.assertNotIn("merge_readiness", plan_report)

    def test_build_plan_report_session_fields_returns_empty_for_unrelated_report(self):
        plan_report = run_orchestration_service.build_plan_report_session_fields(
            {"summary_markdown": "Plan complete", "risks": ["none"]}
        )

        self.assertEqual(plan_report, {})

    def test_build_plan_report_session_update_only_for_fresh_plan_only_runs(self):
        source_report = {
            "branch_slug_candidate": "fix-order-status",
            "execution_policy_decision": {"route": "standard_change"},
            "user_facing_summary": "用户可读计划",
            "technical_summary": "技术计划",
            "next_actions": ["确认计划", "进入实现"],
            "commit_sha": "abc123",
        }

        update = run_orchestration_service.build_plan_report_session_update(
            mode=RunMode.PLAN_ONLY,
            report=source_report,
            stale_completion=False,
        )

        self.assertEqual(
            update,
            {
                "plan_report": {
                    "branch_slug_candidate": "fix-order-status",
                    "execution_policy_decision": {"route": "standard_change"},
                    "user_facing_summary": "用户可读计划",
                    "technical_summary": "技术计划",
                    "next_actions": ["确认计划", "进入实现"],
                }
            },
        )
        self.assertNotIn("commit_sha", update["plan_report"])

        for mode in (RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST):
            with self.subTest(mode=mode):
                self.assertEqual(
                    run_orchestration_service.build_plan_report_session_update(
                        mode=mode,
                        report=source_report,
                        stale_completion=False,
                    ),
                    {},
                )

        self.assertEqual(
            run_orchestration_service.build_plan_report_session_update(
                mode=RunMode.PLAN_ONLY,
                report=source_report,
                stale_completion=True,
            ),
            {},
        )

    def test_build_plan_report_session_update_omits_empty_safe_fields(self):
        self.assertEqual(
            run_orchestration_service.build_plan_report_session_update(
                mode=RunMode.PLAN_ONLY,
                report={"summary_markdown": "Plan complete"},
                stale_completion=False,
            ),
            {},
        )

    def test_build_completion_session_update_combines_plan_report_and_runner_update(self):
        update = run_orchestration_service.build_completion_session_update(
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
            status="succeeded",
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
        self.assertEqual(update["runner"]["attach_command"], "codex resume thread_1")

    def test_build_completion_session_update_omits_plan_report_for_non_plan_modes(self):
        update = run_orchestration_service.build_completion_session_update(
            mode=RunMode.QA,
            report={
                "branch_slug_candidate": "fix-order-status",
                "raw_status": "ready_for_merge_test",
            },
            stale_completion=False,
            runner_name="codex_cli",
            run_id="run_qa",
            status="succeeded",
            session_id="thread_qa",
            run_still_active=False,
            attach_command="codex resume thread_qa",
        )

        self.assertNotIn("plan_report", update)
        self.assertEqual(update["runner"]["last_run_id"], "run_qa")
        self.assertEqual(update["runner"]["resume_session_id"], "thread_qa")

    def test_build_completion_session_update_skips_stale_completion(self):
        update = run_orchestration_service.build_completion_session_update(
            mode=RunMode.PLAN_ONLY,
            report={"branch_slug_candidate": "fix-order-status", "raw_status": "plan_ready"},
            stale_completion=True,
            runner_name="codex_cli",
            run_id="run_stale",
            status="succeeded",
            session_id="thread_stale",
            run_still_active=False,
            attach_command="codex resume thread_stale",
        )

        self.assertEqual(update, {})


if __name__ == "__main__":
    unittest.main()
