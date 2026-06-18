import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from coding_orchestration.models import AgentRunStatus, RunMode, TaskStatus
from coding_orchestration.run_ledger_projection import (
    build_reconciled_run_ledger_writeback_records,
    build_run_ledger_writeback_records,
)


class RunLedgerProjectionTest(unittest.TestCase):
    def test_build_run_ledger_writeback_records_returns_artifact_and_agent_run_without_writing_ledger(self):
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            artifacts = type(
                "Artifacts",
                (),
                {
                    "run_dir": run_dir,
                    "input_prompt": run_dir / "input-prompt.md",
                    "manifest": run_dir / "run-manifest.json",
                    "stdout": run_dir / "stdout.log",
                    "stderr": run_dir / "stderr.log",
                    "events": run_dir / "events.jsonl",
                    "report": run_dir / "report.json",
                    "summary": run_dir / "summary.md",
                    "diff": run_dir / "diff.patch",
                    "operator_log": run_dir / "run-log.md",
                    "execution_policy": run_dir / "execution-policy.json",
                    "context_manifest": run_dir / "context-manifest.json",
                },
            )()

            records = build_run_ledger_writeback_records(
                artifacts=artifacts,
                run_id="run_impl",
                runner_name="codex_cli",
                mode=RunMode.IMPLEMENTATION,
                status=AgentRunStatus.SUCCEEDED.value,
                task_status=TaskStatus.READY_FOR_MERGE_TEST,
                report={"raw_status": "ready_for_merge_test", "structured": False},
                exit_code=0,
                workspace_path="/tmp/worktree",
                source_branch="codex/order-task",
                implementation_checkpoint={"status": "clean"},
                qa_artifacts={},
                tested_commit="",
                stale_completion=False,
                changed_files=["src/app.py"],
                violations=[],
                merge_record_created_at="2026-06-18T10:00:00+00:00",
            )

            self.assertEqual(records.artifact_record["report"], str(run_dir / "report.json"))
            self.assertEqual(records.agent_run_record["run_id"], "run_impl")
            self.assertEqual(records.agent_run_record["artifact"], records.artifact_record)
            self.assertEqual(records.agent_run_record["source_branch"], "codex/order-task")
            self.assertEqual(records.agent_run_record["implementation_checkpoint"], {"status": "clean"})
            self.assertIsNone(records.merge_test_record)

    def test_build_run_ledger_writeback_records_includes_merge_record_only_for_fresh_merge_test(self):
        artifacts = type(
            "Artifacts",
            (),
            {
                "run_dir": Path("/tmp/run"),
                "input_prompt": Path("/tmp/run/input-prompt.md"),
                "manifest": Path("/tmp/run/run-manifest.json"),
                "stdout": Path("/tmp/run/stdout.log"),
                "stderr": Path("/tmp/run/stderr.log"),
                "events": Path("/tmp/run/events.jsonl"),
                "report": Path("/tmp/run/report.json"),
                "summary": Path("/tmp/run/summary.md"),
                "diff": Path("/tmp/run/diff.patch"),
                "operator_log": Path("/tmp/run/run-log.md"),
                "execution_policy": Path("/tmp/run/execution-policy.json"),
                "context_manifest": Path("/tmp/run/context-manifest.json"),
            },
        )()

        records = build_run_ledger_writeback_records(
            artifacts=artifacts,
            run_id="run_merge",
            runner_name="codex_cli",
            mode=RunMode.MERGE_TEST,
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.MERGED_TEST,
            report={},
            exit_code=0,
            workspace_path="/tmp/worktree",
            source_branch="codex/order-task",
            implementation_checkpoint={"status": "clean"},
            qa_artifacts={},
            tested_commit="",
            stale_completion=False,
            changed_files=[],
            violations=[],
            merge_record_created_at="2026-06-18T10:00:00+00:00",
        )
        stale_records = build_run_ledger_writeback_records(
            artifacts=artifacts,
            run_id="run_stale",
            runner_name="codex_cli",
            mode=RunMode.MERGE_TEST,
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.MERGED_TEST,
            report={},
            exit_code=0,
            workspace_path="/tmp/worktree",
            source_branch="codex/order-task",
            implementation_checkpoint=None,
            qa_artifacts={},
            tested_commit="",
            stale_completion=True,
            changed_files=[],
            violations=[],
            merge_record_created_at="2026-06-18T10:00:00+00:00",
        )

        self.assertEqual(
            records.merge_test_record,
            {
                "type": "merge_test_run",
                "run_id": "run_merge",
                "status": AgentRunStatus.SUCCEEDED.value,
                "task_status": TaskStatus.MERGED_TEST.value,
                "source_branch": "codex/order-task",
                "target_branch": "test",
                "artifact": records.artifact_record,
                "created_at": "2026-06-18T10:00:00+00:00",
            },
        )
        self.assertIsNone(stale_records.merge_test_record)

    def test_build_reconciled_run_ledger_writeback_records_returns_artifact_and_merged_agent_run_payload(self):
        artifacts = type(
            "Artifacts",
            (),
            {
                "run_dir": Path("/tmp/reconciled-run"),
                "input_prompt": Path("/tmp/reconciled-run/input-prompt.md"),
                "manifest": Path("/tmp/reconciled-run/run-manifest.json"),
                "stdout": Path("/tmp/reconciled-run/stdout.log"),
                "stderr": Path("/tmp/reconciled-run/stderr.log"),
                "events": Path("/tmp/reconciled-run/events.jsonl"),
                "report": Path("/tmp/reconciled-run/report.json"),
                "summary": Path("/tmp/reconciled-run/summary.md"),
                "diff": Path("/tmp/reconciled-run/diff.patch"),
                "operator_log": Path("/tmp/reconciled-run/run-log.md"),
                "execution_policy": Path("/tmp/reconciled-run/execution-policy.json"),
                "context_manifest": Path("/tmp/reconciled-run/context-manifest.json"),
            },
        )()
        existing_run = {
            "run_id": "run_active",
            "runner": "codex_cli",
            "status": "running",
            "diff_guard": {"violations": ["old_violation"]},
            "qa_artifacts": {"report": "old.md"},
        }

        records = build_reconciled_run_ledger_writeback_records(
            artifacts=artifacts,
            existing_run=existing_run,
            run_id="run_active",
            runner_name="codex_cli",
            mode=RunMode.QA,
            status=AgentRunStatus.SUCCEEDED.value,
            report={
                "raw_status": "ready_for_merge_test",
                "status_detail": "qa passed",
                "qa_artifacts": {"report": "qa-report.md"},
                "tested_commit": "abc123",
            },
            changed_files=["src/app.py"],
        )

        self.assertEqual(records.artifact_record["summary"], "/tmp/reconciled-run/summary.md")
        self.assertEqual(records.agent_run_record["run_id"], "run_active")
        self.assertEqual(records.agent_run_record["artifact"], records.artifact_record)
        self.assertEqual(records.agent_run_record["status"], AgentRunStatus.SUCCEEDED.value)
        self.assertEqual(records.agent_run_record["qa_artifacts"], {"report": "qa-report.md"})
        self.assertEqual(records.agent_run_record["tested_commit"], "abc123")
        self.assertEqual(
            records.agent_run_record["diff_guard"],
            {"changed_files": ["src/app.py"], "violations": ["old_violation"]},
        )


if __name__ == "__main__":
    unittest.main()
