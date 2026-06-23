from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..models import RunMode, task_status_display


def format_task_status_details(task: dict[str, Any], *, include_branch: bool) -> str:
    task_id = str(task.get("task_id") or "")
    session = task.get("task_session") or {}
    lines = [
        f"[{task_id}] 状态：{task_status_display(task.get('status'))}",
        f"项目：{task.get('project_path') or '未确定'}",
    ]
    phase = str(task.get("phase") or "").strip()
    if phase:
        lines.append(f"执行阶段：{phase}")
    latest_run = latest_agent_run(task)
    if latest_run and latest_run.get("status"):
        lines.append(f"最近运行：{latest_run.get('status')}")
    kanban_sync = session.get("kanban_sync") or {}
    if kanban_sync:
        lines.append(f"Kanban 同步：{kanban_sync_status_display(kanban_sync)}")
    completion_notification = session.get("last_completion_notification") or {}
    if completion_notification:
        lines.append(f"完成回传：{completion_notification_status_display(completion_notification)}")
    if include_branch:
        lines.extend(
            [
                f"源分支：{session.get('source_branch') or '未创建'}",
                f"工作区：{session.get('worktree_path') or '未创建'}",
            ]
        )
    _append_qa_details(lines, task)
    return "\n".join(lines)


def format_task_status_payload(payload: dict[str, Any]) -> str:
    task_id = str(payload.get("task_id") or "").strip()
    if not payload.get("ok"):
        error = str(payload.get("error") or "unknown").strip()
        return f"[{task_id or 'unknown'}] 状态：❌ {error}"
    status = str(payload.get("status_display") or payload.get("status_label") or payload.get("status") or "unknown")
    lines = [
        f"[{task_id}] 状态：{status}",
        f"项目：{payload.get('project_path') or payload.get('project_name') or '未确定'}",
    ]
    phase = str(payload.get("phase") or "").strip()
    if phase:
        lines.append(f"执行阶段：{phase}")
    runtime_status = str(payload.get("runtime_status") or "").strip()
    if runtime_status:
        lines.append(f"最近运行：{runtime_status}")
    kanban_sync = payload.get("kanban_sync") or {}
    if isinstance(kanban_sync, dict) and kanban_sync:
        lines.append(f"Kanban 同步：{kanban_sync_status_display(kanban_sync)}")
    source_status = str(payload.get("source_status") or "").strip()
    if source_status:
        lines.append(f"来源状态：{source_status}")
    recovery_action = str(payload.get("source_recovery_action") or "").strip()
    if recovery_action:
        lines.append(f"恢复动作：{recovery_action}")
    next_actions = payload.get("next_actions") or []
    if next_actions:
        lines.append("下一步：" + ", ".join(str(action) for action in next_actions))
    return "\n".join(lines)


def kanban_sync_status_display(kanban_sync: dict[str, Any]) -> str:
    status = str(kanban_sync.get("status") or "").strip()
    label = {
        "ok": "成功",
        "failed": "失败",
        "skipped": "跳过",
    }.get(status, status or "未知")
    reason = str(kanban_sync.get("reason") or "").strip()
    if reason and status in {"failed", "skipped"}:
        return f"{label} - {reason}"
    return label


def completion_notification_status_display(notification: dict[str, Any]) -> str:
    status = str(notification.get("status") or "").strip()
    label = {
        "ok": "成功",
        "scheduled": "已投递",
        "failed": "失败",
        "skipped": "跳过",
    }.get(status, status or "未知")
    run_id = str(notification.get("run_id") or "").strip()
    reason = str(notification.get("reason") or "").strip()
    parts = [label]
    if run_id:
        parts.append(f"执行={run_id}")
    if reason and status in {"failed", "skipped"}:
        parts.append(reason)
    return " - ".join(parts)


def latest_agent_run(task: dict[str, Any]) -> dict[str, Any] | None:
    runs = task.get("agent_runs") or []
    return runs[-1] if runs else None


def latest_qa_run(task: dict[str, Any]) -> dict[str, Any] | None:
    for run in reversed(task.get("agent_runs") or []):
        if run.get("mode") == RunMode.QA.value:
            return run
    return None


def read_report_json(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(str(path_value))
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def qa_health_score_from_report_path(path_value: Any) -> str:
    path = Path(str(path_value))
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"health\s*score\s*[:：]\s*([0-9]+(?:\s*[-→>]+\s*[0-9]+)?)", text, flags=re.I)
    return match.group(1).strip() if match else ""


def _append_qa_details(lines: list[str], task: dict[str, Any]) -> None:
    qa_run = latest_qa_run(task)
    if not qa_run:
        return
    qa_artifacts = qa_run.get("qa_artifacts") or {}
    qa_report_path = str(qa_artifacts.get("report") or "").strip()
    report = read_report_json((qa_run.get("artifact") or {}).get("report"))
    if qa_report_path:
        lines.append(f"QA report：{qa_report_path}")
        health_score = qa_health_score_from_report_path(qa_report_path)
        if health_score:
            lines.append(f"QA health score：{health_score}")
    limitations = report.get("verification_limitations") or []
    if limitations:
        lines.append("已知缺口：")
        for item in limitations[:3]:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or "unknown")
            impact = str(item.get("impact") or "").strip()
            recovery = str(item.get("recovery_action") or "").strip()
            line = f"- {reason}"
            if impact:
                line += f"；影响：{impact}"
            if recovery:
                line += f"；恢复：{recovery}"
            lines.append(line)
