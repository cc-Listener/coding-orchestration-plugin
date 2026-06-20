from __future__ import annotations

from typing import Any

from . import task_list_presenter


def command_coding_list(host: Any, raw_args: str = "") -> str:
    tasks = host.ledger.list_recent_tasks(statuses=host._active_coding_statuses(), limit=20)
    if not tasks:
        return "当前没有未结束开发任务。"
    return format_task_list(tasks)


def task_list_for_event(host: Any, event: Any) -> str:
    binding_key = host._binding_key_for_event(event)
    active_id = host._active_task_id_for_event(event)
    tasks = host.ledger.list_recent_tasks(statuses=host._active_coding_statuses(), limit=10)
    if not tasks:
        return "当前没有未结束开发任务。"
    lines = format_task_list(tasks, active_id=active_id).splitlines()
    if binding_key:
        lines.append(f"提示：当前会话绑定：{active_id or '无'}；使用 /coding use <task_id> 切换当前任务。")
    else:
        lines.append("提示：使用 /coding use <task_id> 切换当前任务。")
    return "\n".join(lines)


def format_task_list(tasks: list[dict[str, Any]], active_id: str | None = None) -> str:
    return task_list_presenter.format_task_list(tasks, active_id=active_id)


def task_project_label(task: dict[str, Any]) -> str:
    return task_list_presenter.task_project_label(task)


def task_description_label(task: dict[str, Any]) -> str:
    return task_list_presenter.task_description_label(task)
