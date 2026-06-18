from __future__ import annotations

import json
from typing import Any

from .common import ConnectionFactory, TaskGetter


class ArtifactRepository:
    def __init__(self, connect: ConnectionFactory, get_task: TaskGetter):
        self._connect = connect
        self._get_task = get_task

    def append_artifact(self, task_id: str, artifact: dict[str, Any]) -> None:
        task = self._get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        artifacts = task["artifacts"]
        artifacts.append(artifact)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set artifacts_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(artifacts, ensure_ascii=False), task_id),
            )

    def upsert_artifact(self, task_id: str, artifact: dict[str, Any]) -> None:
        task = self._get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        artifacts = list(task["artifacts"])
        run_dir = str(artifact.get("run_dir") or "")
        report = str(artifact.get("report") or "")
        replaced = False
        for idx, existing in enumerate(artifacts):
            same_run_dir = run_dir and str(existing.get("run_dir") or "") == run_dir
            same_report = report and str(existing.get("report") or "") == report
            if not same_run_dir and not same_report:
                continue
            updated = dict(existing)
            updated.update(artifact)
            artifacts[idx] = updated
            replaced = True
            break
        if not replaced:
            artifacts.append(artifact)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set artifacts_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(artifacts, ensure_ascii=False), task_id),
            )
