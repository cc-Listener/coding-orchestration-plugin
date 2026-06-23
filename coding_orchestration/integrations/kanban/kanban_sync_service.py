from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models import TaskKind, TaskStatus, task_status_view


def sync_task_to_kanban(
    host: Any,
    *,
    task_id: str,
    title: str,
    body: str,
    project_name: str,
    project_path: str,
    status: str,
) -> dict[str, Any] | None:
    bridge = getattr(host, "kanban_bridge", None)
    if bridge is None or not hasattr(bridge, "create_task"):
        return None
    task = host.ledger.get_task(task_id) or {}
    try:
        result = bridge.create_task(
            local_task_id=task_id,
            title=title or task_id,
            body=body,
            assignee="coder",
            metadata={
                "project": project_name,
                "project_path": project_path,
                "status": status,
                "task_kind": str(task.get("task_kind") or TaskKind.EXECUTION.value),
                "root_task_id": str(task.get("root_task_id") or task_id),
                "parent_task_id": str(task.get("parent_task_id") or ""),
            },
        )
    except Exception as exc:
        return {"ok": False, "reason": f"kanban_sync_failed: {exc}"}
    if result.get("ok") and result.get("kanban_task_id"):
        host.ledger.update_task_session(
            task_id,
            {
                "kanban_task_id": result["kanban_task_id"],
                "kanban": {
                    "task_id": result["kanban_task_id"],
                    "sync_status": "created",
                },
            },
        )
    return result


def sync_status_to_kanban(
    host: Any,
    task_id: str,
    status: TaskStatus | str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    status_value = status.value if isinstance(status, TaskStatus) else str(status)
    status_view = task_status_view(status_value)
    task = host.ledger.get_task(task_id)
    if not task:
        return {
            "status": "skipped",
            "reason": f"task not found: {task_id}",
            **task_status_sync_fields(status_view),
        }
    session = task.get("task_session") or {}
    kanban_task_id = str(session.get("kanban_task_id") or "")
    bridge = getattr(host, "kanban_bridge", None)
    if bridge is None or not hasattr(bridge, "sync_task_status"):
        sync = {"status": "skipped", "reason": "kanban_bridge_unavailable"}
    elif not kanban_task_id:
        sync = {"status": "skipped", "reason": "kanban_task_id_missing"}
    else:
        result = bridge.sync_task_status(
            local_task_id=task_id,
            kanban_task_id=kanban_task_id,
            task_status=status_value,
            reason=reason,
        )
        sync = kanban_sync_record_from_result(result, status_view)
    sync = {
        **sync,
        **task_status_sync_fields(status_view),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    host.ledger.update_task_session(task_id, {"kanban_sync": sync})
    return sync


def kanban_sync_skipped(host: Any, task_id: str, status: str, *, reason: str) -> dict[str, Any]:
    status_view = task_status_view(status)
    sync = {
        "status": "skipped",
        "reason": reason,
        **task_status_sync_fields(status_view),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    host.ledger.update_task_session(task_id, {"kanban_sync": sync})
    return sync


def kanban_sync_record_from_result(result: dict[str, Any], status_view: dict[str, str]) -> dict[str, Any]:
    sync_status = "ok" if result.get("ok") else "failed"
    record = {
        "status": sync_status,
        "tool": result.get("tool") or "",
        "reason": result.get("reason") or "",
    }
    if "raw" in result:
        record["raw"] = result.get("raw")
    return {**record, **task_status_sync_fields(status_view)}


def task_status_sync_fields(status_view: dict[str, str]) -> dict[str, str]:
    return {
        "task_status": status_view["status"],
        "task_status_label_zh": status_view["status_label_zh"],
        "task_status_display": status_view["status_display"],
    }
