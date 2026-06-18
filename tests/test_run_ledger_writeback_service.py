import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run_ledger_projection import (
    ReconciledRunLedgerWritebackRecords,
    RunLedgerWritebackRecords,
)
from coding_orchestration.run_ledger_writeback_service import (
    write_reconciled_run_ledger,
    write_run_ledger_completion,
)
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class RunLedgerWritebackServiceTest(unittest.TestCase):
    def test_write_run_ledger_completion_appends_artifact_agent_run_and_merge_record(self):
        calls = []
        records = RunLedgerWritebackRecords(
            artifact_record={"report": "/tmp/run/report.json"},
            agent_run_record={"run_id": "run_1", "status": AgentRunStatus.SUCCEEDED.value},
            merge_test_record={"type": "merge_test_run", "run_id": "run_1"},
        )

        write_run_ledger_completion(
            task_id="task_1",
            records=records,
            append_artifact_callback=lambda task_id, record: calls.append(("artifact", task_id, record)),
            append_agent_run_callback=lambda task_id, record: calls.append(("agent_run", task_id, record)),
            append_merge_record_callback=lambda task_id, record: calls.append(("merge", task_id, record)),
        )

        self.assertEqual(
            calls,
            [
                ("artifact", "task_1", {"report": "/tmp/run/report.json"}),
                ("agent_run", "task_1", {"run_id": "run_1", "status": AgentRunStatus.SUCCEEDED.value}),
                ("merge", "task_1", {"type": "merge_test_run", "run_id": "run_1"}),
            ],
        )

    def test_write_run_ledger_completion_skips_missing_merge_record(self):
        calls = []
        records = RunLedgerWritebackRecords(
            artifact_record={"summary": "/tmp/run/summary.md"},
            agent_run_record={"run_id": "run_2"},
            merge_test_record=None,
        )

        write_run_ledger_completion(
            task_id="task_2",
            records=records,
            append_artifact_callback=lambda task_id, record: calls.append(("artifact", task_id, record)),
            append_agent_run_callback=lambda task_id, record: calls.append(("agent_run", task_id, record)),
            append_merge_record_callback=lambda task_id, record: calls.append(("merge", task_id, record)),
        )

        self.assertEqual(
            calls,
            [
                ("artifact", "task_2", {"summary": "/tmp/run/summary.md"}),
                ("agent_run", "task_2", {"run_id": "run_2"}),
            ],
        )

    def test_write_reconciled_run_ledger_upserts_artifact_and_agent_run(self):
        calls = []
        records = ReconciledRunLedgerWritebackRecords(
            artifact_record={"report": "/tmp/reconciled/report.json"},
            agent_run_record={"run_id": "run_active", "status": AgentRunStatus.BLOCKED.value},
        )

        write_reconciled_run_ledger(
            task_id="task_3",
            records=records,
            upsert_artifact_callback=lambda task_id, record: calls.append(("artifact", task_id, record)),
            upsert_agent_run_callback=lambda task_id, record: calls.append(("agent_run", task_id, record)),
        )

        self.assertEqual(
            calls,
            [
                ("artifact", "task_3", {"report": "/tmp/reconciled/report.json"}),
                ("agent_run", "task_3", {"run_id": "run_active", "status": AgentRunStatus.BLOCKED.value}),
            ],
        )

    def test_start_run_delegates_ledger_append_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_ledger_writeback"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="生成订单筛选计划",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            calls = []
            original = orchestrator_module.run_ledger_writeback_service.write_run_ledger_completion

            def fake_write_run_ledger_completion(**kwargs):
                calls.append(kwargs)

            try:
                orchestrator_module.run_ledger_writeback_service.write_run_ledger_completion = (
                    fake_write_run_ledger_completion
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["records"].artifact_record["report"], result["artifacts"]["report"])
                self.assertEqual(calls[0]["records"].agent_run_record["run_id"], result["run_id"])
                self.assertIsNone(calls[0]["records"].merge_test_record)
                self.assertTrue(callable(calls[0]["append_artifact_callback"]))
                self.assertTrue(callable(calls[0]["append_agent_run_callback"]))
                self.assertTrue(callable(calls[0]["append_merge_record_callback"]))
            finally:
                orchestrator_module.run_ledger_writeback_service.write_run_ledger_completion = original

    def test_reconcile_completed_active_run_delegates_ledger_upsert_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_reconcile_ledger" / "run_done"
            run_dir.mkdir(parents=True)
            report_path = run_dir / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "后台计划完成",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("后台计划完成", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_path),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_reconcile_ledger"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.PLAN_ONLY.value,
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_done",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.QUEUED.value,
                    "artifact": artifact,
                    "diff_guard": {"changed_files": [], "violations": []},
                },
            )
            ledger.append_artifact(task_id, artifact)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            calls = []
            original = orchestrator_module.run_ledger_writeback_service.write_reconciled_run_ledger

            def fake_write_reconciled_run_ledger(**kwargs):
                calls.append(kwargs)

            try:
                orchestrator_module.run_ledger_writeback_service.write_reconciled_run_ledger = (
                    fake_write_reconciled_run_ledger
                )

                result = orchestrator._reconcile_completed_active_run(task_id)

                self.assertEqual(result["run_id"], "run_done")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["records"].artifact_record["report"], str(report_path))
                self.assertEqual(calls[0]["records"].agent_run_record["run_id"], "run_done")
                self.assertTrue(callable(calls[0]["upsert_artifact_callback"]))
                self.assertTrue(callable(calls[0]["upsert_agent_run_callback"]))
            finally:
                orchestrator_module.run_ledger_writeback_service.write_reconciled_run_ledger = original


if __name__ == "__main__":
    unittest.main()
