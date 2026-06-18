import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus


class RunOrchestrationServiceTest(unittest.TestCase):
    def test_build_agent_run_record_preserves_plan_run_contract(self):
        record = run_orchestration_service.build_agent_run_record(
            run_id="run_1",
            runner_name="codex_cli",
            mode=RunMode.PLAN_ONLY,
            status=AgentRunStatus.SUCCESS.value,
            report={"raw_status": "ready_for_implementation", "known_gaps": True},
            exit_code=0,
            artifact_record={"report": "report.json"},
            workspace_path=None,
            source_branch="codex/source",
            implementation_checkpoint={"status": "clean"},
            qa_artifacts={"report": "qa.json"},
            tested_commit="abc123",
            stale_completion=False,
            changed_files=[],
            violations=[],
        )

        self.assertEqual(record["run_id"], "run_1")
        self.assertEqual(record["runner"], "codex_cli")
        self.assertEqual(record["mode"], RunMode.PLAN_ONLY.value)
        self.assertEqual(record["raw_status"], "ready_for_implementation")
        self.assertTrue(record["known_gaps"])
        self.assertIsNone(record["source_branch"])
        self.assertIsNone(record["target_branch"])
        self.assertIsNone(record["implementation_checkpoint"])
        self.assertEqual(record["qa_artifacts"], {"report": "qa.json"})
        self.assertEqual(record["tested_commit"], "abc123")

    def test_build_agent_run_record_preserves_implementation_fields(self):
        record = run_orchestration_service.build_agent_run_record(
            run_id="run_impl",
            runner_name="codex_cli",
            mode=RunMode.IMPLEMENTATION,
            status=AgentRunStatus.SUCCESS.value,
            report={"failure_type": "", "structured": False},
            exit_code=0,
            artifact_record={},
            workspace_path="/tmp/worktree",
            source_branch="codex/order-task",
            implementation_checkpoint={"status": "clean"},
            qa_artifacts={},
            tested_commit="",
            stale_completion=False,
            changed_files=["src/app.py"],
            violations=["outside allowed path"],
        )

        self.assertEqual(record["workspace_path"], "/tmp/worktree")
        self.assertEqual(record["source_branch"], "codex/order-task")
        self.assertIsNone(record["target_branch"])
        self.assertEqual(record["implementation_checkpoint"], {"status": "clean"})
        self.assertFalse(record["structured"])
        self.assertEqual(
            record["diff_guard"],
            {"changed_files": ["src/app.py"], "violations": ["outside allowed path"]},
        )

    def test_build_agent_run_record_marks_merge_test_target_branch_and_stale_completion(self):
        record = run_orchestration_service.build_agent_run_record(
            run_id="run_merge",
            runner_name="codex_cli",
            mode=RunMode.MERGE_TEST,
            status=AgentRunStatus.SUCCESS.value,
            report={},
            exit_code=0,
            artifact_record={},
            workspace_path="/tmp/worktree",
            source_branch="codex/order-task",
            implementation_checkpoint={"status": "clean"},
            qa_artifacts={},
            tested_commit="",
            stale_completion=True,
            changed_files=[],
            violations=[],
        )

        self.assertEqual(record["source_branch"], "codex/order-task")
        self.assertEqual(record["target_branch"], "test")
        self.assertIsNone(record["implementation_checkpoint"])
        self.assertTrue(record["stale_completion"])

    def test_build_reconciled_agent_run_record_merges_existing_run_contract(self):
        existing_run = {
            "run_id": "run_old",
            "runner": "old_runner",
            "qa_artifacts": {"report": "old-qa.md"},
            "tested_commit": "old-head",
            "diff_guard": {"violations": ["old violation"]},
            "extra": "keep",
        }

        record = run_orchestration_service.build_reconciled_agent_run_record(
            existing_run=existing_run,
            run_id="run_1",
            runner_name="codex_cli",
            mode=RunMode.QA,
            status=AgentRunStatus.SUCCEEDED.value,
            report={
                "raw_status": "ready_for_merge_test",
                "status_detail": "ok",
                "failure_type": "",
                "known_gaps": True,
                "structured": False,
            },
            artifact_record={"report": "report.json"},
            changed_files=["src/app.py"],
        )

        self.assertEqual(existing_run["run_id"], "run_old")
        self.assertEqual(record["extra"], "keep")
        self.assertEqual(record["run_id"], "run_1")
        self.assertEqual(record["runner"], "codex_cli")
        self.assertEqual(record["mode"], RunMode.QA.value)
        self.assertEqual(record["status"], AgentRunStatus.SUCCEEDED.value)
        self.assertEqual(record["raw_status"], "ready_for_merge_test")
        self.assertEqual(record["status_detail"], "ok")
        self.assertTrue(record["known_gaps"])
        self.assertFalse(record["structured"])
        self.assertEqual(record["artifact"], {"report": "report.json"})
        self.assertEqual(record["qa_artifacts"], {"report": "old-qa.md"})
        self.assertEqual(record["tested_commit"], "old-head")
        self.assertFalse(record["stale_completion"])
        self.assertEqual(
            record["diff_guard"],
            {"changed_files": ["src/app.py"], "violations": ["old violation"]},
        )

    def test_build_runner_session_update_preserves_completed_session_resume_fields(self):
        update = run_orchestration_service.build_runner_session_update(
            runner_name="codex_cli",
            run_id="run_1",
            status=AgentRunStatus.SUCCEEDED.value,
            report={"raw_status": "ready_for_merge_test"},
            session_id="thread_1",
            run_still_active=False,
            attach_command="codex attach thread_1",
            reconciled_at="2026-06-17T12:00:00+00:00",
        )

        self.assertEqual(update["provider"], "codex_cli")
        self.assertEqual(update["last_run_id"], "run_1")
        self.assertEqual(update["last_run_status"], AgentRunStatus.SUCCEEDED.value)
        self.assertEqual(update["last_run_raw_status"], "ready_for_merge_test")
        self.assertIsNone(update["active_run_id"])
        self.assertIsNone(update["active_mode"])
        self.assertEqual(update["resume_session_id"], "thread_1")
        self.assertEqual(update["thread_id"], "thread_1")
        self.assertEqual(update["session_id"], "thread_1")
        self.assertEqual(update["attach_command"], "codex attach thread_1")
        self.assertEqual(update["reconciled_run_id"], "run_1")
        self.assertEqual(update["reconciled_at"], "2026-06-17T12:00:00+00:00")

    def test_build_runner_session_update_drops_runner_failed_session_resume_fields(self):
        update = run_orchestration_service.build_runner_session_update(
            runner_name="codex_cli",
            run_id="run_failed",
            status=AgentRunStatus.FAILED.value,
            report={"raw_status": "runner_failed", "failure_type": "runner_failed"},
            session_id="thread_failed",
            run_still_active=False,
            attach_command="codex attach thread_failed",
        )

        self.assertEqual(update["last_run_raw_status"], "runner_failed")
        self.assertEqual(update["resume_session_id"], "")
        self.assertEqual(update["thread_id"], "")
        self.assertEqual(update["session_id"], "")
        self.assertEqual(update["attach_command"], "")

    def test_build_runner_session_update_does_not_clear_still_active_run(self):
        update = run_orchestration_service.build_runner_session_update(
            runner_name="codex_cli",
            run_id="run_active",
            status=AgentRunStatus.RUNNING.value,
            report={"raw_status": "queued"},
            session_id="thread_active",
            run_still_active=True,
            attach_command="codex attach thread_active",
        )

        self.assertEqual(
            update,
            {
                "provider": "codex_cli",
                "last_run_id": "run_active",
                "last_run_status": AgentRunStatus.RUNNING.value,
                "last_run_raw_status": "queued",
            },
        )

    def test_build_merge_test_run_record_preserves_merge_contract(self):
        record = run_orchestration_service.build_merge_test_run_record(
            run_id="run_merge",
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.MERGED_TEST,
            source_branch="codex/order-task",
            artifact_record={"report": "report.json"},
            created_at="2026-06-17T13:00:00+00:00",
        )

        self.assertEqual(
            record,
            {
                "type": "merge_test_run",
                "run_id": "run_merge",
                "status": AgentRunStatus.SUCCEEDED.value,
                "task_status": TaskStatus.MERGED_TEST.value,
                "source_branch": "codex/order-task",
                "target_branch": "test",
                "artifact": {"report": "report.json"},
                "created_at": "2026-06-17T13:00:00+00:00",
            },
        )

    def test_build_project_writeback_payload_preserves_bugfix_completion_contract(self):
        payload = run_orchestration_service.build_project_writeback_payload(
            run_id="run_1",
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.READY_FOR_MERGE_TEST,
            report={"summary_markdown": "实现完成"},
        )

        self.assertEqual(
            payload,
            {
                "run_id": "run_1",
                "status": AgentRunStatus.SUCCEEDED.value,
                "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "report": {"summary_markdown": "实现完成"},
            },
        )

    def test_build_completion_report_payload_preserves_report_writeback_contract(self):
        source_report = {"summary_markdown": "计划完成", "status": "plan_ready"}

        payload = run_orchestration_service.build_completion_report_payload(
            report=source_report,
            status=AgentRunStatus.SUCCESS.value,
            task_status=TaskStatus.PLANNED,
            details={"status": AgentRunStatus.SUCCESS.value, "raw_status": "plan_ready"},
        )

        self.assertEqual(source_report, {"summary_markdown": "计划完成", "status": "plan_ready"})
        self.assertEqual(payload["summary_markdown"], "计划完成")
        self.assertEqual(payload["run_status"], AgentRunStatus.SUCCESS.value)
        self.assertEqual(payload["status"], AgentRunStatus.SUCCESS.value)
        self.assertEqual(payload["task_status"], TaskStatus.PLANNED.value)
        self.assertEqual(payload["raw_status"], "plan_ready")

    def test_project_run_completion_marks_merge_test_human_required_as_known_gap(self):
        projection = run_orchestration_service.project_run_completion(
            mode=RunMode.MERGE_TEST,
            status=AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
            details={"status": AgentRunStatus.COMPLETED_UNSTRUCTURED.value},
            report={"human_required": True},
            running_phase=TaskPhase.READY_TO_MERGE_TEST,
        )

        self.assertEqual(projection.task_status, TaskStatus.READY_FOR_MERGE_TEST)
        self.assertTrue(projection.report["known_gaps"])

    def test_build_start_run_result_payload_preserves_completion_contract(self):
        payload = run_orchestration_service.build_start_run_result_payload(
            task_id="task_1",
            run_id="run_1",
            mode=RunMode.IMPLEMENTATION,
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.READY_FOR_MERGE_TEST,
            stale_completion=False,
            current_task_status=TaskStatus.RUNNING.value,
            observed_active_run_id="run_old",
            artifact_record={"report": "report.json"},
            report={"summary_markdown": "完成"},
            project_writeback={"ok": True},
        )

        self.assertEqual(
            payload,
            {
                "task_id": "task_1",
                "run_id": "run_1",
                "mode": RunMode.IMPLEMENTATION.value,
                "status": AgentRunStatus.SUCCEEDED.value,
                "run_status": AgentRunStatus.SUCCEEDED.value,
                "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "stale_completion": False,
                "current_task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "observed_active_run_id": "",
                "artifacts": {"report": "report.json"},
                "report": {"summary_markdown": "完成"},
                "project_writeback": {"ok": True},
            },
        )

    def test_build_start_run_result_payload_preserves_stale_completion_observation(self):
        payload = run_orchestration_service.build_start_run_result_payload(
            task_id="task_1",
            run_id="run_old",
            mode=RunMode.MERGE_TEST,
            status=AgentRunStatus.SUCCESS.value,
            task_status=TaskStatus.MERGED_TEST,
            stale_completion=True,
            current_task_status=TaskStatus.RUNNING.value,
            observed_active_run_id="run_new",
            artifact_record={"report": "stale-report.json"},
            report={"summary_markdown": "过期完成"},
            project_writeback={"ok": False, "status": "skipped_stale_completion"},
        )

        self.assertEqual(payload["current_task_status"], TaskStatus.RUNNING.value)
        self.assertEqual(payload["observed_active_run_id"], "run_new")
        self.assertEqual(payload["task_status"], TaskStatus.MERGED_TEST.value)
        self.assertEqual(payload["project_writeback"], {"ok": False, "status": "skipped_stale_completion"})

    def test_build_reconcile_result_payload_preserves_active_run_completion_contract(self):
        payload = run_orchestration_service.build_reconcile_result_payload(
            task_id="task_1",
            run_id="run_1",
            mode=RunMode.QA,
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.READY_FOR_MERGE_TEST,
            artifact_record={"report": "report.json"},
        )

        self.assertEqual(
            payload,
            {
                "task_id": "task_1",
                "run_id": "run_1",
                "mode": RunMode.QA.value,
                "status": AgentRunStatus.SUCCEEDED.value,
                "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "artifacts": {"report": "report.json"},
                "reconciled": True,
            },
        )

    def test_project_run_completion_maps_plan_success_to_planned(self):
        projection = run_orchestration_service.project_run_completion(
            mode=RunMode.PLAN_ONLY,
            status=AgentRunStatus.SUCCESS.value,
            details={"status": AgentRunStatus.SUCCESS.value},
            report={"summary_markdown": "计划完成"},
            running_phase=TaskPhase.PLANNING,
        )

        self.assertEqual(projection.status, AgentRunStatus.SUCCESS.value)
        self.assertEqual(projection.task_status, TaskStatus.PLANNED)
        self.assertEqual(projection.task_phase, TaskPhase.PLAN_READY)
        self.assertFalse(projection.run_still_active)
        self.assertEqual(projection.report["run_status"], AgentRunStatus.SUCCESS.value)
        self.assertEqual(projection.report["task_status"], TaskStatus.PLANNED.value)
        self.assertEqual(projection.report["summary_markdown"], "计划完成")

    def test_project_run_completion_preserves_running_phase_for_active_run(self):
        projection = run_orchestration_service.project_run_completion(
            mode=RunMode.IMPLEMENTATION,
            status=AgentRunStatus.RUNNING.value,
            details={"status": AgentRunStatus.RUNNING.value},
            report={},
            running_phase=TaskPhase.IMPLEMENTING,
        )

        self.assertEqual(projection.task_status, TaskStatus.RUNNING)
        self.assertEqual(projection.task_phase, TaskPhase.IMPLEMENTING)
        self.assertTrue(projection.run_still_active)
        self.assertEqual(projection.report["task_status"], TaskStatus.RUNNING.value)

    def test_project_run_completion_keeps_merge_test_human_required_ready_for_retry(self):
        projection = run_orchestration_service.project_run_completion(
            mode=RunMode.MERGE_TEST,
            status=AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
            details={"status": AgentRunStatus.COMPLETED_UNSTRUCTURED.value},
            report={"human_required": True},
            running_phase=TaskPhase.READY_TO_MERGE_TEST,
        )

        self.assertEqual(projection.task_status, TaskStatus.READY_FOR_MERGE_TEST)
        self.assertEqual(projection.task_phase, TaskPhase.READY_TO_MERGE_TEST)
        self.assertEqual(projection.report["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)

    def test_project_run_completion_does_not_release_failed_merge_test_human_required(self):
        projection = run_orchestration_service.project_run_completion(
            mode=RunMode.MERGE_TEST,
            status=AgentRunStatus.FAILED.value,
            details={"status": AgentRunStatus.FAILED.value},
            report={"human_required": True},
            running_phase=TaskPhase.READY_TO_MERGE_TEST,
        )

        self.assertEqual(projection.task_status, TaskStatus.FAILED)
        self.assertEqual(projection.task_phase, TaskPhase.FAILED)

if __name__ == "__main__":
    unittest.main()
