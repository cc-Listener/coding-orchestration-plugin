from __future__ import annotations

from typing import Any

from .models import RunMode
from .project_resolver import normalize_text as normalize_project_text


def handle_pending_action_gateway_message(
    host: Any,
    text: str,
    event: Any,
    gateway: Any,
    *,
    include_latest_human_required: bool,
) -> dict[str, str] | None:
    normalized = normalize_project_text(text)
    pending = host._pending_action_for_event(event)
    from_binding = pending is not None
    if pending is None and include_latest_human_required and host._is_human_confirmation_reply(normalized):
        pending = pending_action_from_latest_human_required_run(host, event)
    if pending is None:
        return None
    if host._is_human_cancellation_reply(normalized):
        if from_binding:
            host._clear_pending_action_for_event(event)
        host._reply_if_possible(gateway, event, "已取消当前待确认动作，未启动新的执行。")
        return {"action": "skip", "reason": "coding_pending_action_cancelled"}
    if host._is_human_confirmation_reply(normalized):
        if from_binding:
            host._clear_pending_action_for_event(event)
        task_id = str(pending.get("task_id") or "").strip()
        task = host.ledger.get_task(task_id) if task_id else None
        if task is not None and host._task_is_cancelled(task):
            host._reply_if_possible(gateway, event, host._cancelled_task_message(task))
            return {"action": "skip", "reason": "coding_pending_action_cancelled_task"}
        host._record_pending_action_confirmation(pending, normalized, event)
        command_text = str(pending.get("command_text") or "").strip()
        handled = host._handle_explicit_gateway_command(command_text, event, gateway)
        if handled is None:
            host._reply_if_possible(
                gateway,
                event,
                f"未执行：待确认动作已失效。\n候选命令：{command_text or '无'}\n请重新描述或直接发送 /coding <action>。",
            )
        return {"action": "skip", "reason": "coding_pending_action_confirmed"}
    if from_binding:
        host._clear_pending_action_for_event(event)
    return None


def pending_action_from_latest_human_required_run(host: Any, event: Any | None) -> dict[str, Any] | None:
    task = host._active_task_for_event(event)
    if task is None:
        return None
    for run in reversed(task.get("agent_runs") or []):
        if run.get("mode") != RunMode.MERGE_TEST.value:
            continue
        report = host._read_report_json((run.get("artifact") or {}).get("report"))
        if not bool(report.get("human_required")):
            return None
        task_id = str(task.get("task_id") or "")
        qa_evidence = host._qa_evidence_for_merge_test(task)
        qa_flag = " --confirm-qa-risk" if qa_evidence.get("requires_confirmation") == "true" else ""
        return {
            "task_id": task_id,
            "action": "merge_test_retry",
            "command_text": f"/coding merge-test {task_id}{qa_flag}",
            "reason": normalize_project_text(str(report.get("summary_markdown") or "merge-test 需要人工确认")),
            "run_id": str(run.get("run_id") or ""),
            "mode": RunMode.MERGE_TEST.value,
        }
    return None
