from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import (
    run_orchestration_service,
    run_reconcile_writeback_service,
    run_report_artifact_service,
    run_summary_artifact_service,
)
from ..models import AgentRunStatus, RunnerName


class OrchestratorActiveRunFacadeMixin:
    def _reconcile_completed_active_run(
        self,
        task_id: str,
        *,
        task: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        task = task or self.ledger.get_task(task_id)
        if not task or self._task_is_cancelled(task):
            return None
        session = task.get("task_session") or {}
        runner_session = session.get("runner") or {}
        run_id = str(runner_session.get("active_run_id") or "").strip()
        if not run_id:
            return None
        run = self._agent_run_for_id(task, run_id) or {}
        artifacts = self._artifact_set_for_existing_run(task_id, run_id, run)
        report = run_report_artifact_service.read_run_report_artifact(report_path=artifacts.report)
        if not report:
            return None
        mode = run_orchestration_service.run_mode_for_existing_run(task, run, report)
        details = self._run_status_details_from_report(report, mode)
        status = str(details["status"])
        if status == AgentRunStatus.RUNNING.value:
            return None

        changed_files = run_orchestration_service.changed_files_for_existing_run(run, report)
        report = dict(report)
        report["modified_files"] = changed_files
        details = self._normalize_implementation_run_status(report, mode)
        status = str(details["status"])
        report.update(details)
        runner_name = str(
            run.get("runner")
            or runner_session.get("provider")
            or report.get("runner")
            or RunnerName.CODEX_CLI.value
        )
        report["runner"] = runner_name
        report.setdefault("mode", mode.value)
        report["modified_files"] = changed_files
        report = self._ensure_verification_limitations(report, status, artifacts)
        run_report_artifact_service.write_run_report_artifact(report_path=artifacts.report, report=report)
        summary = str(report.get("summary_markdown") or "").strip()
        if summary:
            run_summary_artifact_service.write_run_summary_artifact(summary_path=artifacts.summary, summary=summary)

        session_id = self._thread_id_from_artifact(artifacts.stdout) or self._codex_resume_session_id_for_task(task)
        result = run_reconcile_writeback_service.write_reconciled_run_finalization(
            task_id=task_id,
            run_id=run_id,
            task=task,
            session=session,
            existing_run=run,
            artifacts=artifacts,
            mode=mode,
            running_phase=self.run_service.running_phase_for_mode(mode),
            status=status,
            details=details,
            report=report,
            changed_files=changed_files,
            runner_name=runner_name,
            session_id=session_id,
            attach_command=self._codex_attach_command(session_id) if session_id else "",
            reconciled_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            write_report_artifact_callback=run_report_artifact_service.write_run_report_artifact,
            transition_task_status_callback=self._transition_task_status,
            upsert_artifact_callback=self.ledger.upsert_artifact,
            upsert_agent_run_callback=self.ledger.upsert_agent_run,
            update_task_session_callback=self.ledger.update_task_session,
            write_summary_callback=self.summary_writer.write_run_summary,
        )
        return result.result_payload

    @staticmethod
    def _agent_run_for_id(task: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        for run in reversed(task.get("agent_runs") or []):
            if str(run.get("run_id") or "") == run_id:
                return run
        return None
