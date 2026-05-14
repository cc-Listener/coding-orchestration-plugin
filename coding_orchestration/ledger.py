from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class TaskLedger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists tasks (
                    task_id text primary key,
                    source_json text not null,
                    requirement_summary text not null,
                    project_path text,
                    status text not null,
                    llm_wiki_refs_json text not null,
                    agent_runs_json text not null,
                    artifacts_json text not null,
                    human_decisions_json text not null,
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp
                )
                """
            )

    def create_task(
        self,
        *,
        task_id: str,
        source: dict[str, Any],
        requirement_summary: str,
        project_path: str | None,
        status: str,
        llm_wiki_refs: list[dict[str, Any]],
        human_decisions: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into tasks (
                    task_id, source_json, requirement_summary, project_path, status,
                    llm_wiki_refs_json, agent_runs_json, artifacts_json, human_decisions_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    json.dumps(source, ensure_ascii=False),
                    requirement_summary,
                    project_path,
                    status,
                    json.dumps(llm_wiki_refs, ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    json.dumps(human_decisions, ensure_ascii=False),
                ),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("select * from tasks where task_id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_recent_tasks(self, *, statuses: list[str] | set[str] | tuple[str, ...] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, int(limit))
        params: list[Any] = []
        where = ""
        if statuses:
            status_values = [str(status) for status in statuses]
            placeholders = ", ".join("?" for _ in status_values)
            where = f"where status in ({placeholders})"
            params.extend(status_values)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from tasks
                {where}
                order by updated_at desc, created_at desc, task_id desc
                limit ?
                """,
                params,
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_status(self, task_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "update tasks set status = ?, updated_at = current_timestamp where task_id = ?",
                (status, task_id),
            )

    def update_requirement_summary(self, task_id: str, requirement_summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set requirement_summary = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (requirement_summary, task_id),
            )

    def replace_llm_wiki_refs(self, task_id: str, refs: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set llm_wiki_refs_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(refs, ensure_ascii=False), task_id),
            )

    def append_agent_run(self, task_id: str, run: dict[str, Any]) -> None:
        task = self.get_task(task_id)
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

    def append_artifact(self, task_id: str, artifact: dict[str, Any]) -> None:
        task = self.get_task(task_id)
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

    def append_human_decision(self, task_id: str, decision: dict[str, Any]) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        decisions = task["human_decisions"]
        decisions.append(decision)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set human_decisions_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(decisions, ensure_ascii=False), task_id),
            )

    def mark_cancelled(self, task_or_run_id: str) -> bool:
        task = self.get_task(task_or_run_id)
        if not task:
            return False
        with self._connect() as conn:
            conn.execute(
                "update tasks set status = 'cancelled', updated_at = current_timestamp where task_id = ?",
                (task_or_run_id,),
            )
        return True

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "source": json.loads(row["source_json"]),
            "requirement_summary": row["requirement_summary"],
            "project_path": row["project_path"],
            "status": row["status"],
            "llm_wiki_refs": json.loads(row["llm_wiki_refs_json"]),
            "agent_runs": json.loads(row["agent_runs_json"]),
            "artifacts": json.loads(row["artifacts_json"]),
            "human_decisions": json.loads(row["human_decisions_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
