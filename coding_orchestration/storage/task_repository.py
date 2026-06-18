from __future__ import annotations

import json
from typing import Any

from .common import ConnectionFactory, deep_merge, row_to_task


class TaskRepository:
    def __init__(self, connect: ConnectionFactory):
        self._connect = connect

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
        source_branch: str | None = None,
        branch_policy: str | None = None,
    ) -> None:
        next_task_session = dict(task_session or {})
        if source_branch:
            next_task_session["source_branch"] = source_branch
        if branch_policy:
            next_task_session["branch_policy"] = branch_policy
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
                    json.dumps(next_task_session, ensure_ascii=False),
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
        return row_to_task(row) if row else None

    def list_recent_tasks(
        self,
        *,
        statuses: list[str] | set[str] | tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
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
        return [row_to_task(row) for row in rows]

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
        return [row_to_task(row) for row in rows]

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
        return [row_to_task(row) for row in rows]

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
        deep_merge(session, updates)
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
        return cursor.rowcount > 0
