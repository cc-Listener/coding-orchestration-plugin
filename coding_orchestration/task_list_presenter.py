from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import task_status_display
from .project_resolver import normalize_text as normalize_project_text


def format_task_list(tasks: list[dict[str, Any]], active_id: str | None = None) -> str:
    lines = ["当前未结束开发任务："]
    for index, task in enumerate(tasks):
        if index > 0:
            lines.append("")
        marker = "*" if active_id and task["task_id"] == active_id else ""
        task_id = f"{marker}{task['task_id']}" if marker else str(task["task_id"])
        lines.append(
            f"任务：{task_id}\n"
            f"状态：{task_status_display(task.get('status'))}\n"
            f"项目：{task_project_label(task)}\n"
            f"任务描述：{task_description_label(task)}"
        )
    return "\n".join(lines)


def task_project_label(task: dict[str, Any]) -> str:
    source = task.get("source") or {}
    session = task.get("task_session") or {}
    project_name = source.get("project_name") or session.get("project_name")
    if project_name:
        return str(project_name)
    project_path = task.get("project_path")
    if project_path:
        return Path(str(project_path)).name
    return "未确定"


def task_description_label(task: dict[str, Any]) -> str:
    summary = normalize_project_text(str(task.get("requirement_summary") or ""))
    if not summary:
        return "未填写"
    summary = re.sub(r"##\s*人工(?:计划|实现)?反馈.*$", "", summary, flags=re.S).strip()
    summary = re.sub(r"需要支持以下功能[:：]?", "支持", summary)
    summary = re.sub(r"\s*[1-9][、.．]\s*", "；", summary)
    parts = [part.strip(" ：:；，,。") for part in summary.split("；") if part.strip(" ：:；，,。")]
    if len(parts) > 1 and parts[0].endswith("支持"):
        first_item = parts[1].split("，", 1)[0].strip(" ：:；，,。")
        summary = f"{parts[0]}{first_item}"
    elif parts:
        summary = parts[0]
    replacements = {
        "的订单列表的": "订单列表",
        "批量绑定商品弹窗": "批量绑定商品弹窗",
        "变体ID、商品名称两种方式的搜索": "变体ID/商品名称搜索",
        "变体ID、商品名称": "变体ID/商品名称",
    }
    for old, new in replacements.items():
        summary = summary.replace(old, new)
    summary = re.sub(r"搜索商品现在要支持", "支持", summary)
    summary = summary.replace("支持支持", "支持")
    summary = re.sub(r"\s+", "", summary)
    return summary if len(summary) <= 42 else f"{summary[:39]}..."
