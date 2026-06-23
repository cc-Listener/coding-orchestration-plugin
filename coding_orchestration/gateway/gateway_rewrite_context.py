from __future__ import annotations

from typing import Any, Callable, Iterable

from ..models import TaskPhase, TaskStatus, canonical_task_status, task_status_display


TaskLabeler = Callable[[dict[str, Any]], str]


def build_coding_rewrite_context(
    *,
    user_text: str,
    active_task: dict[str, Any] | None,
    known_tasks: Iterable[dict[str, Any]],
    active_project: dict[str, Any] | None,
    known_projects: Iterable[dict[str, Any]],
    media: Iterable[dict[str, Any]],
    recommended_skill: str,
    command_catalog: Iterable[dict[str, Any]],
    allowed_commands: Iterable[dict[str, Any]],
    project_label: TaskLabeler,
    summary_label: TaskLabeler,
) -> dict[str, Any]:
    media_items = list(media)
    known_task_items = list(known_tasks)
    return {
        "user_text": user_text,
        "coding_mode_enabled": True,
        "active_task": _task_rewrite_context(
            active_task,
            has_active_project=bool(active_project),
            project_label=project_label,
            summary_label=summary_label,
            include_status_label=True,
        )
        if active_task
        else None,
        "known_task_ids": [str(task.get("task_id") or "") for task in known_task_items if task.get("task_id")],
        "known_tasks": [
            _task_rewrite_context(
                task,
                has_active_project=bool(active_project),
                project_label=project_label,
                summary_label=summary_label,
                include_status_label=False,
            )
            for task in known_task_items
        ],
        "active_project": active_project,
        "known_projects": list(known_projects),
        "recommended_skill": recommended_skill,
        "command_catalog": list(command_catalog),
        "has_media": bool(media_items),
        "media_types": [str(item.get("type") or "") for item in media_items if item.get("type")],
        "allowed_commands": list(allowed_commands),
    }


def task_next_step_hint(task: dict[str, Any], *, has_active_project: bool = False) -> str:
    task_id = str(task.get("task_id") or "<task_id>")
    raw_status = str(task.get("status") or "")
    status = (canonical_task_status(raw_status) or TaskStatus.NEW).value
    phase = str(task.get("phase") or "")
    if raw_status == TaskStatus.CANCELLED.value:
        return f"只能使用 /coding restore {task_id} 恢复误取消任务。"
    if status == TaskStatus.RUNNING.value:
        return "已有执行正在进行；不要启动新执行，先查看当前执行或等待完成。"
    if not task.get("project_path"):
        if has_active_project:
            return (
                f"任务缺少项目，但当前会话已有项目；可使用 /coding run {task_id} "
                "自动补齐项目并重新整理计划。"
            )
        return f"任务缺少项目；先使用 /coding continue <项目或来源补充>。"
    if status == TaskStatus.NEEDS_HUMAN.value:
        return f"先使用 /coding continue <项目或来源补充> 补齐人工信息。"
    if status == TaskStatus.PLANNED.value and phase in {TaskPhase.PLAN_READY.value, TaskPhase.PLAN_APPROVED.value}:
        return f"计划已可执行；使用 /coding implement {task_id}。"
    if status == TaskStatus.PLANNED.value:
        return f"计划仍需刷新或确认；使用 /coding run {task_id}。"
    if status == TaskStatus.FAILED.value:
        return f"项目已确定；使用 /coding run {task_id} 重新整理计划，或查看 /coding status {task_id}。"
    if status == TaskStatus.BLOCKED.value:
        return (
            f"先查看 /coding status {task_id} 的影响和建议；"
            f"若确认目标改动已完成且接受风险，可使用 /coding merge-test {task_id} --accept-risk。"
        )
    if status == TaskStatus.READY_FOR_MERGE_TEST.value:
        return f"使用 /coding merge-test {task_id}。"
    if status == TaskStatus.MERGED_TEST.value:
        return f"人工验收 test 后使用 /coding complete {task_id}。"
    if status == TaskStatus.DONE.value:
        return "任务已完成；无需继续操作。"
    return f"先查看 /coding status {task_id}。"


def _task_rewrite_context(
    task: dict[str, Any] | None,
    *,
    has_active_project: bool,
    project_label: TaskLabeler,
    summary_label: TaskLabeler,
    include_status_label: bool,
) -> dict[str, Any] | None:
    if not task:
        return None
    context = {
        "task_id": str(task.get("task_id") or ""),
        "status": str(task.get("status") or ""),
        "phase": str(task.get("phase") or ""),
        "project": project_label(task),
        "summary": summary_label(task),
        "next_step": task_next_step_hint(task, has_active_project=has_active_project),
    }
    if include_status_label:
        context["status_label"] = task_status_display(task.get("status"))
    return context
