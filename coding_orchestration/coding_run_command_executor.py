from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import RunMode, TaskPhase


def command_coding_run(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    try:
        result = host.start_run(task_id, mode=RunMode.PLAN_ONLY)
    except ValueError as exc:
        return str(exc)
    return host._format_run_completion_message(task_id, result)


def command_coding_implement(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    if host._task_is_cancelled(task):
        return host._cancelled_task_message(task)
    if not host._task_is_plan_ready_for_implementation(task):
        host.ledger.append_human_decision(
            task_id,
            {
                "type": "implementation_command_before_plan_ready",
                "text": raw_args,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return host._implementation_blocked_before_plan_ready_message(task)
    host.ledger.update_phase(task_id, TaskPhase.PLAN_APPROVED.value)
    result = host.start_run(task_id, mode=RunMode.IMPLEMENTATION)
    return host._format_implementation_completion_message(task_id, result)


def command_coding_qa(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    blocked = host._qa_start_blocker(task)
    if blocked:
        return blocked
    host._record_qa_request(task_id, f"/coding qa {task_id}", event=None)
    result = host.start_run(task_id, mode=RunMode.QA)
    return host._format_qa_completion_message(task_id, result)
