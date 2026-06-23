from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from ...models import AgentRunStatus, RunMode, TaskPhase, TaskStatus, normalize_agent_run_status
from ...project_resolver import normalize_text as normalize_project_text


def wait_for_background_run_completion(
    host: Any,
    task_id: str,
    result: dict[str, Any],
    *,
    mode: RunMode,
) -> dict[str, Any]:
    status = normalize_agent_run_status(result.get("status"), mode)
    if status not in {AgentRunStatus.QUEUED.value, AgentRunStatus.RUNNING.value}:
        return result
    run_id = str(result.get("run_id") or "").strip()
    if not run_id:
        return result

    deadline = time.monotonic() + host._timeout_seconds_for_mode(mode) + 60
    while True:
        task = host.ledger.get_task(task_id)
        if not task:
            return result
        runner = (task.get("task_session") or {}).get("runner") or {}
        active_run_id = str(runner.get("active_run_id") or "").strip()
        if active_run_id and active_run_id != run_id:
            return result

        reconciled = host._reconcile_completed_active_run(task_id, task=task)
        if reconciled:
            return reconciled
        if time.monotonic() >= deadline:
            return result
        time.sleep(2)


def mark_background_run_failed(host: Any, task_id: str, exc: Exception, *, mode: RunMode) -> None:
    try:
        task = host.ledger.get_task(task_id) or {}
        current_status = str(task.get("status") or "")
        if current_status in {
            TaskStatus.NEEDS_HUMAN.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.MERGED_TEST.value,
            TaskStatus.DONE.value,
        }:
            return
        host._transition_task_status(
            task_id,
            TaskStatus.FAILED,
            phase=TaskPhase.RUNNER_FAILED,
            reason=f"{mode.value} startup failed: {exc}",
        )
    except ValueError as transition_exc:
        try:
            host.ledger.append_human_decision(
                task_id,
                {
                    "type": "background_failure_transition_rejected",
                    "mode": mode.value,
                    "error": str(exc),
                    "transition_error": str(transition_exc),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            pass
    except Exception:
        pass


def store_pending_action_from_merge_test_result(
    host: Any,
    event: Any | None,
    task_id: str,
    result: dict[str, Any],
) -> bool:
    artifacts = result.get("artifacts") or {}
    report = host._read_report_json(artifacts.get("report"))
    if not bool(report.get("human_required")):
        return False
    task = host.ledger.get_task(task_id) or {}
    qa_evidence = host._qa_evidence_for_merge_test(task) if task else {}
    qa_flag = " --confirm-qa-risk" if qa_evidence.get("requires_confirmation") == "true" else ""
    return host._store_pending_action_for_event(
        event,
        task_id=task_id,
        action="merge_test_retry",
        command_text=f"/coding merge-test {task_id}{qa_flag}",
        reason=normalize_project_text(str(report.get("summary_markdown") or "merge-test 需要人工确认")),
        run_id=str(result.get("run_id") or ""),
        mode=RunMode.MERGE_TEST.value,
    )
