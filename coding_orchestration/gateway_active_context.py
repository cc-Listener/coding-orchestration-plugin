from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def apply_active_project_to_task_if_missing(host: Any, task: dict[str, Any], event: Any | None) -> dict[str, Any]:
    if task.get("project_path"):
        return task
    active_project = host._active_project_for_event(event)
    if not active_project:
        return task
    project_name = str(active_project.get("name") or active_project.get("project") or "").strip()
    project_path = str(active_project.get("path") or "").strip()
    if not project_name or not project_path:
        return task
    evidence = [{"source": "active_project", "value": project_name, "score": 1.0}]
    host.ledger.update_project_context(
        task["task_id"],
        project_name=project_name,
        project_path=project_path,
        confidence=1.0,
        match_evidence=evidence,
    )
    host.ledger.append_human_decision(
        task["task_id"],
        {
            "type": "project_context_applied_from_active_project",
            "project_name": project_name,
            "project_path": project_path,
            "gateway_source": host._event_source_for_ledger(event),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return host.ledger.get_task(task["task_id"]) or task
