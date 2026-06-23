from __future__ import annotations

import json
from typing import Any

from ..project.project_workitem_binding import ProjectWorkitemIdentity
from .common import ConnectionFactory, row_to_project_workitem_binding


class BindingRepository:
    def __init__(self, connect: ConnectionFactory):
        self._connect = connect

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

    def delete_active_bindings_for_task(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from active_task_bindings where task_id = ?", (task_id,))

    def upsert_project_workitem_binding(
        self,
        *,
        identity: ProjectWorkitemIdentity,
        hermes_task_id: str,
        relation_kind: str,
        source_workitem_key: str | None = None,
        root_task_id: str | None = None,
        parent_task_id: str | None = None,
        external_status: str = "",
        writeback_status: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into project_workitem_bindings (
                    project_workitem_key, hermes_task_id, relation_kind,
                    source_workitem_key, root_task_id, parent_task_id,
                    domain, space_key, workitem_type, workitem_id,
                    workitem_url, workitem_title, identity_confidence,
                    external_status, writeback_status, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(project_workitem_key) do update set
                    hermes_task_id = excluded.hermes_task_id,
                    relation_kind = excluded.relation_kind,
                    source_workitem_key = excluded.source_workitem_key,
                    root_task_id = excluded.root_task_id,
                    parent_task_id = excluded.parent_task_id,
                    domain = excluded.domain,
                    space_key = excluded.space_key,
                    workitem_type = excluded.workitem_type,
                    workitem_id = excluded.workitem_id,
                    workitem_url = excluded.workitem_url,
                    workitem_title = excluded.workitem_title,
                    identity_confidence = excluded.identity_confidence,
                    external_status = excluded.external_status,
                    writeback_status = excluded.writeback_status,
                    metadata_json = excluded.metadata_json,
                    updated_at = current_timestamp
                """,
                (
                    identity.key,
                    hermes_task_id,
                    relation_kind,
                    source_workitem_key,
                    root_task_id,
                    parent_task_id,
                    identity.domain.rstrip("/"),
                    identity.space_key,
                    identity.workitem_type,
                    identity.workitem_id,
                    identity.url,
                    identity.title,
                    identity.identity_confidence,
                    external_status,
                    writeback_status,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )

    def find_task_id_by_project_workitem_url(self, url: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "select hermes_task_id from project_workitem_bindings where workitem_url = ?",
                (url,),
            ).fetchone()
        return str(row["hermes_task_id"]) if row else None

    def find_project_workitem_binding(self, project_workitem_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from project_workitem_bindings where project_workitem_key = ?",
                (project_workitem_key,),
            ).fetchone()
        return row_to_project_workitem_binding(row) if row else None

    def list_project_workitem_bindings(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from project_workitem_bindings
                where hermes_task_id = ? or root_task_id = ?
                order by created_at asc, project_workitem_key asc
                """,
                (task_id, task_id),
            ).fetchall()
        return [row_to_project_workitem_binding(row) for row in rows]
