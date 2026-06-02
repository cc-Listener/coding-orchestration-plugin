from __future__ import annotations

from typing import Any, Callable


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

    @staticmethod
    def _normalize_create_result(result: Any) -> dict[str, Any]:
        task_id = ""
        if isinstance(result, dict):
            task_id = str(result.get("task_id") or result.get("id") or "")
        return {"ok": bool(task_id), "kanban_task_id": task_id, "raw": result}
