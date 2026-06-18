from __future__ import annotations

import json
from typing import Any

from .common import ConnectionFactory, TaskGetter


class RunRepository:
    def __init__(self, connect: ConnectionFactory, get_task: TaskGetter):
        self._connect = connect
        self._get_task = get_task

    def append_agent_run(self, task_id: str, run: dict[str, Any]) -> None:
        task = self._get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        runs = task["agent_runs"]
        runs.append(run)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set agent_runs_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(runs, ensure_ascii=False), task_id),
            )

    def upsert_agent_run(self, task_id: str, run: dict[str, Any]) -> None:
        task = self._get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        runs = list(task["agent_runs"])
        run_id = str(run.get("run_id") or "")
        replaced = False
        if run_id:
            for idx, existing in enumerate(runs):
                if str(existing.get("run_id") or "") != run_id:
                    continue
                updated = dict(existing)
                updated.update(run)
                runs[idx] = updated
                replaced = True
                break
        if not replaced:
            runs.append(run)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set agent_runs_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(runs, ensure_ascii=False), task_id),
            )
