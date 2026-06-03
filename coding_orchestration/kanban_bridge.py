from __future__ import annotations

from typing import Any, Callable

from .models import TaskStatus, task_status_view


class KanbanBridge:
    def __init__(self, dispatch_tool: Callable[[str, dict[str, Any]], Any] | None = None):
        self.dispatch_tool = dispatch_tool

    def available(self) -> bool:
        return callable(self.dispatch_tool)

    def create_task(
        self,
        *,
        local_task_id: str,
        title: str,
        body: str,
        assignee: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "reason": "kanban_dispatch_unavailable"}
        payload = {
            "title": title,
            "body": body,
            "assignee": assignee,
            "idempotency_key": f"coding:{local_task_id}",
            "metadata": {"local_task_id": local_task_id, **metadata},
        }
        result = self.dispatch_tool("kanban_create", payload)
        return self._normalize_create_result(result)

    def sync_task_status(
        self,
        *,
        local_task_id: str,
        kanban_task_id: str,
        task_status: TaskStatus | str,
        reason: str = "",
    ) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "reason": "kanban_dispatch_unavailable"}
        if not kanban_task_id:
            return {"ok": False, "reason": "kanban_task_id_missing"}

        status_view = task_status_view(task_status)
        tool = self._tool_for_task_status(status_view["status"])
        payload = {
            "task_id": kanban_task_id,
            "comment": self._status_comment(status_view, reason),
            "metadata": {
                "local_task_id": local_task_id,
                "task_status": status_view["status"],
                "task_status_label_zh": status_view["status_label_zh"],
                "task_status_display": status_view["status_display"],
                "reason": reason,
            },
        }
        try:
            result = self.dispatch_tool(tool, payload)
        except Exception as exc:
            return {
                "ok": False,
                "tool": tool,
                "reason": f"kanban_sync_failed: {exc}",
                "task_status": status_view["status"],
                "task_status_label_zh": status_view["status_label_zh"],
                "task_status_display": status_view["status_display"],
                **status_view,
            }
        return {
            "ok": True,
            "tool": tool,
            "raw": result,
            "task_status": status_view["status"],
            "task_status_label_zh": status_view["status_label_zh"],
            "task_status_display": status_view["status_display"],
            **status_view,
        }

    @staticmethod
    def _tool_for_task_status(task_status: str) -> str:
        if task_status == TaskStatus.DONE.value:
            return "kanban_complete"
        if task_status == TaskStatus.BLOCKED.value:
            return "kanban_block"
        if task_status in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
            return "kanban_heartbeat"
        return "kanban_comment"

    @staticmethod
    def _status_comment(status_view: dict[str, str], reason: str) -> str:
        if reason:
            return f"状态投影：{status_view['status_display']}；原因：{reason}"
        return f"状态投影：{status_view['status_display']}"

    @staticmethod
    def _normalize_create_result(result: Any) -> dict[str, Any]:
        task_id = ""
        if isinstance(result, dict):
            task_id = str(result.get("task_id") or result.get("id") or "")
        return {"ok": bool(task_id), "kanban_task_id": task_id, "raw": result}
