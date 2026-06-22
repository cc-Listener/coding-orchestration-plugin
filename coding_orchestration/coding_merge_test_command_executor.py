from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import gateway_command_controller, merge_test_presenter, run_completion_presenter
from .models import RunMode, TaskPhase, TaskStatus


def command_prepare_merge_test(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    if host._task_is_cancelled(task):
        return host._cancelled_task_message(task)
    blocked_assessment = None
    if task["status"] == TaskStatus.BLOCKED.value:
        blocked_assessment = host._blocked_task_merge_test_assessment(task)
        if blocked_assessment.get("mergeable") and blocked_assessment.get("requires_acceptance"):
            return host._blocked_merge_test_risk_confirmation_message(task_id, blocked_assessment)
    status_update = status_update_for_prepare_merge_test(host, task, assessment=blocked_assessment)
    if task["status"] not in {
        TaskStatus.READY_FOR_MERGE_TEST.value,
    } and status_update is None:
        return merge_test_presenter.prepare_merge_test_invalid_status_message(task_id, task)
    if status_update is not None:
        host._transition_task_status(
            task_id,
            status_update,
            phase=TaskPhase.READY_TO_MERGE_TEST,
            reason="prepare merge-test from blocked task",
        )
    else:
        host.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
    known_gaps = bool(status_update is not None)
    host.ledger.append_merge_record(
        task_id,
        {
            "type": "merge_test_prepared",
            "status": "ready",
            "target_branch": "test",
            "known_gaps": known_gaps,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return merge_test_presenter.prepare_merge_test_ready_message(task_id, task)


def status_update_for_prepare_merge_test(
    host: Any,
    task: dict[str, Any],
    *,
    assessment: dict[str, Any] | None = None,
) -> TaskStatus | None:
    status = str(task.get("status") or "")
    if status != TaskStatus.BLOCKED.value:
        return None
    assessment = assessment if assessment is not None else host._blocked_task_merge_test_assessment(task)
    return TaskStatus.READY_FOR_MERGE_TEST if assessment.get("mergeable") else None


def command_coding_merge_test(host: Any, raw_args: str) -> str:
    parsed_args = gateway_command_controller.parse_merge_test_command_args(raw_args)
    accept_risk = parsed_args.accept_risk
    confirm_qa_risk = parsed_args.confirm_qa_risk
    task_id = parsed_args.task_id
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    assessment = host._blocked_task_merge_test_assessment(task)
    if assessment.get("requires_acceptance") and not accept_risk:
        return host._blocked_merge_test_risk_confirmation_message(task_id, assessment)
    release = host._release_blocked_task_for_merge_test_if_allowed(task, accept_risk=accept_risk)
    if release:
        task = host.ledger.get_task(task_id) or task
    blocked = host._merge_test_blocker(task)
    if blocked:
        return blocked
    qa_evidence = host._qa_evidence_for_merge_test(task)
    if qa_evidence.get("requires_confirmation") == "true" and not confirm_qa_risk:
        return host._merge_test_qa_risk_confirmation_message(task_id, qa_evidence, include_reply_hint=False)
    host.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
    host.ledger.append_merge_record(
        task_id,
        {
            "type": "merge_test_requested",
            "status": "running",
            "target_branch": "test",
            "qa_evidence": qa_evidence,
            "blocked_release": release,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    result = host.start_run(task_id, mode=RunMode.MERGE_TEST)
    message = run_completion_presenter.format_merge_test_completion_message(task_id, result)
    if release:
        message = f"{message}\n\n{host._blocked_merge_test_release_note(release)}"
    if qa_evidence.get("message"):
        message = f"{message}\n\nQA 证据：{qa_evidence['message']}"
    return message
