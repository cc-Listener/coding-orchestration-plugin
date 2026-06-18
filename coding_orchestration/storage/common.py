from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any


ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]
TaskGetter = Callable[[str], dict[str, Any] | None]


def deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    task_session = json.loads(row["task_session_json"])
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
        "task_session": task_session,
        "source_branch": task_session.get("source_branch"),
        "branch_policy": task_session.get("branch_policy"),
        "merge_records": json.loads(row["merge_records_json"]),
        "task_kind": row["task_kind"],
        "root_task_id": row["root_task_id"] or row["task_id"],
        "parent_task_id": row["parent_task_id"],
        "dependency_task_ids": json.loads(row["dependency_task_ids_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_project_workitem_binding(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "project_workitem_key": row["project_workitem_key"],
        "hermes_task_id": row["hermes_task_id"],
        "relation_kind": row["relation_kind"],
        "source_workitem_key": row["source_workitem_key"],
        "root_task_id": row["root_task_id"],
        "parent_task_id": row["parent_task_id"],
        "domain": row["domain"],
        "space_key": row["space_key"],
        "workitem_type": row["workitem_type"],
        "workitem_id": row["workitem_id"],
        "workitem_url": row["workitem_url"],
        "workitem_title": row["workitem_title"],
        "identity_confidence": row["identity_confidence"],
        "external_status": row["external_status"],
        "writeback_status": row["writeback_status"],
        "metadata": json.loads(row["metadata_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
