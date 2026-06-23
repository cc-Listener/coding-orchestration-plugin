import unittest

from coding_orchestration.run.projections.run_summary_projection import (
    build_completed_run_summary_writeback_payload,
    build_reconciled_run_summary_writeback_payload,
)


class RunSummaryProjectionTest(unittest.TestCase):
    def test_build_reconciled_run_summary_writeback_payload_prefers_session_project_and_copies_report(self):
        report = {"summary_markdown": "实现完成", "status": "succeeded"}

        payload = build_reconciled_run_summary_writeback_payload(
            task_id="task_1",
            run_id="run_1",
            task={"source": {"project_name": "source-project"}},
            session={"project_name": "session-project"},
            merged_run={"runner": "codex_cli"},
            report=report,
            summary="实现完成",
        )
        report["status"] = "mutated"

        self.assertEqual(
            payload.as_kwargs(),
            {
                "task_id": "task_1",
                "run_id": "run_1",
                "runner": "codex_cli",
                "project": "session-project",
                "report": {"summary_markdown": "实现完成", "status": "succeeded"},
                "summary": "实现完成",
            },
        )

    def test_build_reconciled_run_summary_writeback_payload_falls_back_to_source_project(self):
        payload = build_reconciled_run_summary_writeback_payload(
            task_id="task_2",
            run_id="run_2",
            task={"source": {"project_name": "source-project"}},
            session={},
            merged_run={"runner": "codex_cli"},
            report={},
            summary="",
        )

        self.assertEqual(payload.project, "source-project")

    def test_build_completed_run_summary_writeback_payload_uses_start_run_context_and_copies_report(self):
        report = {"summary_markdown": "QA 完成", "status": "ready_for_merge_test"}

        payload = build_completed_run_summary_writeback_payload(
            task_id="task_3",
            run_id="run_3",
            runner="codex_cli",
            project_name="orders-admin",
            report=report,
            summary="QA 完成",
        )
        report["status"] = "mutated"

        self.assertEqual(
            payload.as_kwargs(),
            {
                "task_id": "task_3",
                "run_id": "run_3",
                "runner": "codex_cli",
                "project": "orders-admin",
                "report": {"summary_markdown": "QA 完成", "status": "ready_for_merge_test"},
                "summary": "QA 完成",
            },
        )

    def test_build_completed_run_summary_writeback_payload_normalizes_empty_values(self):
        payload = build_completed_run_summary_writeback_payload(
            task_id="task_4",
            run_id="run_4",
            runner=None,
            project_name=None,
            report={},
            summary="",
        )

        self.assertEqual(payload.runner, "")
        self.assertEqual(payload.project, "")


if __name__ == "__main__":
    unittest.main()
