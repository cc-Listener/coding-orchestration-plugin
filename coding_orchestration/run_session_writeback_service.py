from __future__ import annotations

from typing import Any, Callable

SessionWritebackCallback = Callable[[str, dict[str, Any]], None]


def write_run_session_update(
    *,
    task_id: str,
    update: dict[str, Any],
    update_task_session_callback: SessionWritebackCallback,
) -> None:
    if not update:
        return
    update_task_session_callback(task_id, update)
