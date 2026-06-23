from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import merge_test_presenter, merge_test_readiness_service, task_status_presenter
from ..models import AgentRunStatus, RunMode, TaskPhase, TaskStatus


class OrchestratorMergeTestFacadeMixin:
    def _merge_test_blocker(self, task: dict[str, Any]) -> str:
        task_id = str(task.get("task_id") or "")
        if task.get("status") not in {
            TaskStatus.READY_FOR_MERGE_TEST.value,
        }:
            if self._task_is_cancelled(task):
                return self._cancelled_task_message(task)
            if task.get("status") == TaskStatus.BLOCKED.value:
                assessment = self._blocked_task_merge_test_assessment(task)
                return merge_test_presenter.merge_test_blocked_validation_message(task_id, assessment)
            return merge_test_presenter.merge_test_invalid_status_message(task)
        if self._merge_test_workspace(task) is None:
            return merge_test_presenter.merge_test_missing_workspace_message(task)
        return ""

    def _release_blocked_task_for_merge_test_if_allowed(
        self,
        task: dict[str, Any],
        *,
        accept_risk: bool = False,
    ) -> dict[str, Any]:
        assessment = self._blocked_task_merge_test_assessment(task)
        if not assessment.get("mergeable") and not (accept_risk and assessment.get("requires_acceptance")):
            return {}
        task_id = str(task.get("task_id") or "")
        release = {
            "type": "blocked_merge_test_released",
            "status": "ready",
            "target_branch": "test",
            "known_gaps": True,
            "accepted_risk": bool(accept_risk and assessment.get("requires_acceptance")),
            "source_run_id": assessment.get("source_run_id") or "",
            "reason": assessment.get("reason") or "blocked_with_mergeable_known_gaps",
            "impact": assessment.get("impact") or "存在已知验证缺口，merge-test 需要人工承担风险。",
            "recovery_action": assessment.get("recovery_action") or "按 report 中恢复动作补充验证。",
            "fallback_evidence": assessment.get("fallback_evidence") or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._transition_task_status(
            task_id,
            TaskStatus.READY_FOR_MERGE_TEST,
            phase=TaskPhase.READY_TO_MERGE_TEST,
            reason=release["reason"],
        )
        self.ledger.append_merge_record(task_id, release)
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "blocked_merge_test_release",
                "reason": release["reason"],
                "impact": release["impact"],
                "recovery_action": release["recovery_action"],
                "fallback_evidence": release["fallback_evidence"],
                "accepted_risk": release["accepted_risk"],
                "created_at": release["created_at"],
            },
        )
        return release

    def _blocked_task_merge_test_assessment(self, task: dict[str, Any]) -> dict[str, Any]:
        run = self._latest_implementation_run(task)
        merge_test_workspace = self._merge_test_workspace(task)
        return merge_test_readiness_service.assess_blocked_merge_test(
            task=task,
            implementation_run=run,
            has_merge_test_workspace=merge_test_workspace is not None,
            source_branch=self._source_branch_for_blocked_merge_test(task, run) if run else "",
            resume_session_id=self._codex_resume_session_id_for_task(task),
            report=self._read_report_json((run.get("artifact") or {}).get("report")) if run else None,
            merge_test_workspace_path=str(merge_test_workspace or ""),
        )

    @staticmethod
    def _latest_implementation_run(task: dict[str, Any]) -> dict[str, Any] | None:
        return merge_test_readiness_service.latest_implementation_run(task)

    @staticmethod
    def _source_branch_for_blocked_merge_test(task: dict[str, Any], run: dict[str, Any]) -> str:
        return merge_test_readiness_service.source_branch_for_blocked_merge_test(task, run)

    @staticmethod
    def _disallowed_blocked_merge_test_reason(run: dict[str, Any]) -> str:
        return merge_test_readiness_service.disallowed_blocked_merge_test_reason(run)

    def _qa_evidence_for_merge_test(self, task: dict[str, Any]) -> dict[str, str]:
        qa_run = task_status_presenter.latest_qa_run(task)
        if not qa_run:
            return {
                "status": "missing",
                "message": "未发现 QA 证据；本次 merge-test 仍按人工触发继续。",
            }
        qa_artifacts = qa_run.get("qa_artifacts") or {}
        report_path = str(qa_artifacts.get("report") or "")
        report = self._read_report_json((qa_run.get("artifact") or {}).get("report"))
        limitations = [item for item in report.get("verification_limitations") or [] if isinstance(item, dict)]
        limitation = limitations[0] if limitations else {}
        status = str(qa_run.get("status") or "unknown")
        detail_source = dict(report)
        for key in ("status", "raw_status", "status_detail", "failure_type", "known_gaps", "structured"):
            if key in qa_run:
                detail_source[key] = qa_run[key]
        details = self._run_status_details_from_report(
            detail_source,
            RunMode.QA,
            fallback_status=status,
        )
        session = task.get("task_session") or {}
        current_head = self._git_head(Path(str(session.get("worktree_path"))) if session.get("worktree_path") else None)
        tested_commit = str(qa_run.get("tested_commit") or report.get("tested_commit") or "")
        evidence = {
            "status": status,
            "run_id": str(qa_run.get("run_id") or ""),
            "report": report_path,
            "message": f"最近 QA 执行={qa_run.get('run_id') or 'unknown'}，状态={status}"
            + (f"，report={report_path}" if report_path else ""),
        }
        if tested_commit and current_head and tested_commit != current_head:
            evidence.update(
                {
                    "status": "stale",
                    "message": f"QA 证据已过期：tested_commit={tested_commit}，当前 HEAD={current_head}",
                    "impact": "QA run 未覆盖当前 source branch HEAD。",
                    "recovery_action": "重新运行 QA，或人工确认该提交差异不影响 merge-test。",
                }
            )
        if (
            details.get("status") in {AgentRunStatus.FAILED.value, AgentRunStatus.BLOCKED.value}
            or details.get("known_gaps")
            or str(details.get("failure_type") or "")
            or details.get("status_detail") == "ready_for_merge_test_with_known_gaps"
        ):
            evidence.update(
                {
                    "requires_confirmation": "true",
                    "impact": str(limitation.get("impact") or ""),
                    "recovery_action": str(limitation.get("recovery_action") or ""),
                }
            )
        return evidence
