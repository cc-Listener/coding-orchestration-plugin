from __future__ import annotations

from typing import Any

from .models import task_status_display
from .project_resolver import normalize_text as normalize_project_text


def format_rewrite_confirmation_message(command_text: str, rewrite: dict[str, Any]) -> str:
    reason = normalize_project_text(str(rewrite.get("reason") or ""))
    lines = [
        "我理解你要执行：",
        "",
        command_text,
    ]
    if reason:
        lines.extend(["", f"理由：{reason}"])
    lines.extend(["", "回复“确认”执行，或回复“取消”放弃。"])
    return "\n".join(lines)


def format_rewrite_needs_human_confirmation_message(
    text: str,
    rewrite: dict[str, Any],
    rejection: str,
) -> str:
    del rewrite
    rejection_text = rewrite_rejection_user_text(rejection)
    return "\n".join(
        [
            "我还不能确定要执行哪个 coding 动作，所以没有创建任务，也没有启动 Codex。",
            f"原话：{text}",
            f"需要补充：{rejection_text}",
            "请补充项目或直接发送 /coding task --project <项目名> <完整需求>。",
        ]
    )


def rewrite_rejection_user_text(rejection: str) -> str:
    normalized = normalize_project_text(str(rejection or ""))
    if not normalized:
        return "请补充项目、任务目标或要执行的动作。"
    internal_markers = ("置信度", "LLM", "canonical_command", "command_rewriter", "JSON", "阈值")
    if any(marker in normalized for marker in internal_markers):
        return "请补充项目、任务目标或要执行的动作。"
    if "缺少必要信息" in normalized:
        return "请补充项目、任务目标或要执行的动作。"
    return normalized


def format_rewrite_handoff_to_hermes_message(
    text: str,
    context: dict[str, Any],
    rejection: str,
) -> str:
    lines = [
        "我还不能确定这句话要创建或操作哪个开发任务，所以没有创建任务，也没有启动执行。",
        "",
        f"原话：{text}",
        f"- 需要补充：{rewrite_rejection_user_text(rejection)}",
    ]
    active_project = context.get("active_project")
    if isinstance(active_project, dict) and active_project:
        project_name = str(active_project.get("name") or active_project.get("project") or "").strip()
        if project_name:
            lines.append(f"- 当前项目：{project_name}")
    active_task = context.get("active_task")
    if isinstance(active_task, dict) and active_task:
        task_summary = normalize_project_text(str(active_task.get("summary") or ""))
        task_line = (
            f"- 当前任务：{active_task.get('task_id') or '未知'}，"
            f"状态 {active_task.get('status_label') or active_task.get('status') or '未知'}"
        )
        project = str(active_task.get("project") or "").strip()
        if project:
            task_line += f"，项目 {project}"
        if task_summary:
            task_line += f"，摘要：{task_summary}"
        lines.append(task_line)
        next_step = normalize_project_text(str(active_task.get("next_step") or ""))
        if next_step:
            lines.append(f"- 当前任务建议下一步：{next_step}")
    known_tasks = context.get("known_tasks")
    if isinstance(known_tasks, list) and known_tasks:
        task_lines = []
        for task in known_tasks[:3]:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "").strip()
            if not task_id:
                continue
            summary = normalize_project_text(str(task.get("summary") or ""))
            status = task_status_display(task.get("status"))
            item = f"{task_id}（{status}）"
            if summary:
                item += f"：{summary}"
            task_lines.append(item)
        if task_lines:
            lines.append(f"- 最近相关任务：{'；'.join(task_lines)}")
    lines.extend(
        [
            "- 可用入口：/coding task --project <项目名> <完整需求>、/coding run <task_id>、/coding implement <task_id>、/coding status <task_id>。",
            "- 如果这不是开发任务操作，可以直接继续普通对话；如果要进入开发流程，请补充项目、任务目标或明确命令。",
            "- 当前没有创建任务、启动执行或执行 /coding 命令。",
        ]
    )
    return "\n".join(lines)
