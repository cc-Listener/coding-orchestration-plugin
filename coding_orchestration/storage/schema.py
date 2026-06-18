from __future__ import annotations

import sqlite3


def initialize_ledger_schema(conn: sqlite3.Connection) -> None:
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
    ensure_column(conn, "tasks", "phase", "text not null default 'draft'")
    ensure_column(conn, "tasks", "task_session_json", "text not null default '{}'")
    ensure_column(conn, "tasks", "merge_records_json", "text not null default '[]'")
    ensure_column(conn, "tasks", "task_kind", "text not null default 'execution'")
    ensure_column(conn, "tasks", "root_task_id", "text")
    ensure_column(conn, "tasks", "parent_task_id", "text")
    ensure_column(conn, "tasks", "dependency_task_ids_json", "text not null default '[]'")
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
    conn.execute(
        """
        create table if not exists project_workitem_bindings (
            project_workitem_key text primary key,
            hermes_task_id text not null,
            relation_kind text not null,
            source_workitem_key text,
            root_task_id text,
            parent_task_id text,
            domain text not null,
            space_key text not null,
            workitem_type text not null,
            workitem_id text not null,
            workitem_url text not null,
            workitem_title text not null default '',
            identity_confidence text not null default 'high',
            external_status text not null default '',
            writeback_status text not null default '',
            metadata_json text not null default '{}',
            created_at text not null default current_timestamp,
            updated_at text not null default current_timestamp
        )
        """
    )
    conn.execute(
        "create index if not exists idx_project_workitem_bindings_task on project_workitem_bindings(hermes_task_id)"
    )
    conn.execute(
        "create index if not exists idx_project_workitem_bindings_root on project_workitem_bindings(root_task_id)"
    )
    conn.execute(
        "create index if not exists idx_project_workitem_bindings_source on project_workitem_bindings(source_workitem_key)"
    )
    conn.execute(
        "create unique index if not exists idx_project_workitem_bindings_url on project_workitem_bindings(workitem_url)"
    )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    if any(row["name"] == column for row in rows):
        return
    conn.execute(f"alter table {table} add column {column} {definition}")
