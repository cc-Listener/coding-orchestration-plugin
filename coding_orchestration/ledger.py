from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class TaskLedger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
            self._ensure_column(conn, "tasks", "phase", "text not null default 'draft'")
            self._ensure_column(conn, "tasks", "task_session_json", "text not null default '{}'")
            self._ensure_column(conn, "tasks", "merge_records_json", "text not null default '[]'")
            self._ensure_column(conn, "tasks", "task_kind", "text not null default 'execution'")
            self._ensure_column(conn, "tasks", "root_task_id", "text")
            self._ensure_column(conn, "tasks", "parent_task_id", "text")
            self._ensure_column(conn, "tasks", "dependency_task_ids_json", "text not null default '[]'")
            conn.execute("create index if not exists idx_tasks_root_task_id on tasks(root_task_id)")
            conn.execute("create index if not exists idx_tasks_parent_task_id on tasks(parent_task_id)")
            conn.execute(
                """
                create table if not exists active_task_bindings (
                    binding_key text primary key,
                    task_id text not null,
                    scope_json text not null,
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp
                )
                """
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"pragma table_info({table})").fetchall()
        if any(row["name"] == column for row in rows):
            return
        conn.execute(f"alter table {table} add column {column} {definition}")

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
        phase: str = "draft",
        task_session: dict[str, Any] | None = None,
        merge_records: list[dict[str, Any]] | None = None,
        task_kind: str = "execution",
        root_task_id: str | None = None,
        parent_task_id: str | None = None,
        dependency_task_ids: list[str] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into tasks (
                    task_id, source_json, requirement_summary, project_path, status,
                    llm_wiki_refs_json, agent_runs_json, artifacts_json, human_decisions_json,
                    phase, task_session_json, merge_records_json,
                    task_kind, root_task_id, parent_task_id, dependency_task_ids_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    phase,
                    json.dumps(task_session or {}, ensure_ascii=False),
                    json.dumps(merge_records or [], ensure_ascii=False),
                    task_kind,
                    root_task_id or task_id,
                    parent_task_id,
                    json.dumps(dependency_task_ids or [], ensure_ascii=False),
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

    def list_child_tasks(self, parent_task_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from tasks
                where parent_task_id = ?
                order by created_at asc, task_id asc
                """,
                (parent_task_id,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def list_root_tasks(self, root_task_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from tasks
                where root_task_id = ?
                order by created_at asc, task_id asc
                """,
                (root_task_id,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_status(self, task_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "update tasks set status = ?, updated_at = current_timestamp where task_id = ?",
                (status, task_id),
            )

    def update_phase(self, task_id: str, phase: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "update tasks set phase = ?, updated_at = current_timestamp where task_id = ?",
                (phase, task_id),
            )

    def update_task_session(self, task_id: str, updates: dict[str, Any]) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        session = dict(task.get("task_session") or {})
        self._deep_merge(session, updates)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set task_session_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(session, ensure_ascii=False), task_id),
            )

    def append_merge_record(self, task_id: str, record: dict[str, Any]) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        records = list(task.get("merge_records") or [])
        records.append(record)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set merge_records_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(records, ensure_ascii=False), task_id),
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

    def update_task_hierarchy(
        self,
        task_id: str,
        *,
        task_kind: str | None = None,
        root_task_id: str | None = None,
        parent_task_id: str | None = None,
        dependency_task_ids: list[str] | None = None,
    ) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        next_task_kind = task_kind if task_kind is not None else task.get("task_kind")
        next_root_task_id = root_task_id if root_task_id is not None else task.get("root_task_id")
        next_parent_task_id = parent_task_id if parent_task_id is not None else task.get("parent_task_id")
        next_dependency_task_ids = (
            dependency_task_ids
            if dependency_task_ids is not None
            else list(task.get("dependency_task_ids") or [])
        )
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set task_kind = ?,
                    root_task_id = ?,
                    parent_task_id = ?,
                    dependency_task_ids_json = ?,
                    updated_at = current_timestamp
                where task_id = ?
                """,
                (
                    str(next_task_kind or "execution"),
                    str(next_root_task_id or task_id),
                    next_parent_task_id,
                    json.dumps(next_dependency_task_ids, ensure_ascii=False),
                    task_id,
                ),
            )

    def update_source_context(self, task_id: str, source_context: dict[str, Any]) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        source = dict(task.get("source") or {})
        source["source_context"] = source_context
        source_type = source_context.get("source_type")
        if source_type:
            source["type"] = source_type
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set source_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (json.dumps(source, ensure_ascii=False), task_id),
            )

    def update_project_context(
        self,
        task_id: str,
        *,
        project_name: str,
        project_path: str,
        confidence: float,
        match_evidence: list[dict[str, Any]],
    ) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        source = dict(task.get("source") or {})
        source["project_name"] = project_name
        source["project_confidence"] = confidence
        source["match_evidence"] = match_evidence
        session = dict(task.get("task_session") or {})
        session["project_name"] = project_name
        with self._connect() as conn:
            conn.execute(
                """
                update tasks
                set source_json = ?, project_path = ?, task_session_json = ?, updated_at = current_timestamp
                where task_id = ?
                """,
                (
                    json.dumps(source, ensure_ascii=False),
                    project_path,
                    json.dumps(session, ensure_ascii=False),
                    task_id,
                ),
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

    def upsert_agent_run(self, task_id: str, run: dict[str, Any]) -> None:
        task = self.get_task(task_id)
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

    def upsert_artifact(self, task_id: str, artifact: dict[str, Any]) -> None:
        task = self.get_task(task_id)
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
                """
                update tasks
                set status = 'cancelled', phase = 'cancelled', updated_at = current_timestamp
                where task_id = ?
                """,
                (task_or_run_id,),
            )
        return True

    def delete_task(self, task_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("delete from tasks where task_id = ?", (task_id,))
            conn.execute("delete from active_task_bindings where task_id = ?", (task_id,))
        return cursor.rowcount > 0

    def bind_active_task(self, *, binding_key: str, task_id: str, scope: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into active_task_bindings (binding_key, task_id, scope_json)
                values (?, ?, ?)
                on conflict(binding_key) do update set
                    task_id = excluded.task_id,
                    scope_json = excluded.scope_json,
                    updated_at = current_timestamp
                """,
                (binding_key, task_id, json.dumps(scope, ensure_ascii=False)),
            )

    def get_active_binding(self, binding_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from active_task_bindings where binding_key = ?",
                (binding_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "binding_key": row["binding_key"],
            "task_id": row["task_id"],
            "scope": json.loads(row["scope_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def clear_active_binding(self, binding_key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "delete from active_task_bindings where binding_key = ?",
                (binding_key,),
            )
        return cursor.rowcount > 0

    @staticmethod
    def _deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                TaskLedger._deep_merge(target[key], value)
            else:
                target[key] = value

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
            "phase": row["phase"],
            "task_session": json.loads(row["task_session_json"]),
            "merge_records": json.loads(row["merge_records_json"]),
            "task_kind": row["task_kind"],
            "root_task_id": row["root_task_id"] or row["task_id"],
            "parent_task_id": row["parent_task_id"],
            "dependency_task_ids": json.loads(row["dependency_task_ids_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
