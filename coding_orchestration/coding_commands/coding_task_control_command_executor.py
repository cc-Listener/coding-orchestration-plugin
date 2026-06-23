from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import TaskPhase, TaskStatus, task_status_display


def command_coding_use(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "命令模式缺少飞书来源，无法绑定当前任务；请在飞书里使用 /coding use <task_id>。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    return (
        f"[{task_id}] 任务存在，但当前命令入口没有飞书来源，未绑定当前任务。\n"
        "请在飞书会话中使用 /coding use <task_id> 完成任务切换。"
    )


def command_coding_exit(host: Any, raw_args: str = "") -> str:
    return "命令模式缺少飞书来源，无法退出指定会话；请在飞书里使用 /coding exit。"


def select_active_task_for_event(host: Any, task_id: str, event: Any) -> str:
    task_id = task_id.strip()
    if not task_id:
        return "请提供任务 ID，例如 /coding use <task_id>。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    if not host._bind_active_task_for_event(task_id, event):
        return f"[{task_id}] 当前来源无法绑定任务。"
    return (
        f"[{task_id}] 已切换当前开发任务。\n"
        f"状态：{task_status_display(task.get('status'))}\n"
        "后续可继续使用 /coding 前缀；若已发送“进入coding”，本会话自然语言也会按当前开发任务处理。"
    )


def clear_active_task_for_event(host: Any, event: Any) -> str:
    if not host._binding_key_for_event(event):
        return "当前来源无法识别，没有可退出的当前任务。"
    cleared = host.gateway_binding_service.clear_active_task_for_event(event)
    mode_cleared = host._disable_coding_mode_for_event(event)
    pending_cleared = host._clear_pending_rewrite_for_event(event)
    action_cleared = host._clear_pending_action_for_event(event)
    return (
        "已退出当前飞书会话的 coding 模式。"
        if cleared or mode_cleared or pending_cleared or action_cleared
        else "当前飞书会话没有绑定开发任务。"
    )


def command_coding_cancel(host: Any, raw_args: str) -> str:
    target = raw_args.strip()
    if not target:
        return "请提供任务 ID 或执行 ID。"
    task = host.ledger.get_task(target)
    if task:
        try:
            host._transition_task_status(
                target,
                TaskStatus.CANCELLED,
                phase=TaskPhase.CANCELLED,
                reason="manual cancellation",
            )
        except ValueError as exc:
            return f"[{target}] 不能取消：{exc}"
        return f"已标记取消：{target}"
    changed = host.ledger.mark_cancelled(target)
    return f"已标记取消：{target}" if changed else f"未找到可取消对象：{target}"


def command_coding_restore(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    if not host._task_is_cancelled(task):
        return f"[{task_id}] 当前状态是 {task_status_display(task.get('status'))}，不需要恢复。"
    status, phase, reason = host._restore_state_for_cancelled_task(task)
    host._transition_task_status(task_id, status, phase=phase, reason=reason)
    host.ledger.update_task_session(
        task_id,
        {
            "runner": {
                "active_run_id": None,
                "active_mode": None,
            }
        },
    )
    host.ledger.append_human_decision(
        task_id,
        {
            "type": "task_restored",
            "previous_status": TaskStatus.CANCELLED.value,
            "previous_phase": TaskPhase.CANCELLED.value,
            "restored_status": status.value,
            "restored_phase": phase.value,
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return (
        f"[{task_id}] 已恢复误取消的开发任务。\n"
        f"状态：{task_status_display(status)}\n"
        f"恢复依据：{reason}\n"
        "说明：本次只恢复任务状态，不会自动启动执行。"
    )


def command_coding_delete(host: Any, raw_args: str) -> str:
    args = raw_args.split()
    purge_artifacts = "--keep-artifacts" not in args
    purge_wiki = "--keep-wiki" not in args
    force = "--force" in args
    task_ids = [arg for arg in args if not arg.startswith("--")]
    if not task_ids:
        return "请提供任务 ID，例如 /coding delete <task_id>。"
    task_id = task_ids[0]
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    if str(task.get("status") or "") == TaskStatus.RUNNING.value and not force:
        return f"[{task_id}] 当前任务正在运行，请先 /coding cancel {task_id}，或使用 /coding delete {task_id} --force。"
    cleaned_paths = host._purge_task_artifacts(task) if purge_artifacts else []
    deleted_wiki_docs = host.wiki.delete_by_source_task(task_id) if purge_wiki else 0
    deleted = host.ledger.delete_task(task_id)
    if not deleted:
        return f"未找到任务：{task_id}"
    lines = [
        f"[{task_id}] 已删除开发任务。",
        "已清理任务记录和当前会话绑定。",
    ]
    if purge_wiki:
        lines.append(f"已清理任务关联上下文：{deleted_wiki_docs} 条。")
    else:
        lines.append("已按 --keep-wiki 保留任务关联上下文。")
    if purge_artifacts:
        lines.append(f"已清理本地执行文件：{len(cleaned_paths)} 个路径。")
    else:
        lines.append("已按 --keep-artifacts 保留本地执行和工作区文件。")
    return "\n".join(lines)


def command_coding_complete(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    current_status = str(task.get("status") or "")
    if current_status != TaskStatus.MERGED_TEST.value:
        return f"[{task_id}] 当前状态是 {task_status_display(current_status)}，不能标记完成；请先执行 /coding merge-test {task_id}。"
    host._transition_task_status(
        task_id,
        TaskStatus.DONE,
        phase=TaskPhase.DONE,
        reason="manual completion",
    )
    host.ledger.append_human_decision(
        task_id,
        {
            "type": "task_completed",
            "previous_status": current_status,
            "previous_phase": task.get("phase"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return f"[{task_id}] 已人工标记完成。\n状态：{task_status_display(TaskStatus.DONE)}"
