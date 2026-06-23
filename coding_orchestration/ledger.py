from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .project.project_workitem_binding import ProjectWorkitemIdentity
from .storage.repositories import ArtifactRepository, BindingRepository, RunRepository, TaskRepository
from .storage.schema import initialize_ledger_schema


class TaskLedger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.task_repository = TaskRepository(self._connect)
        self.run_repository = RunRepository(self._connect, self.get_task)
        self.artifact_repository = ArtifactRepository(self._connect, self.get_task)
        self.binding_repository = BindingRepository(self._connect)

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
            initialize_ledger_schema(conn)

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
        self.task_repository.create_task(
            task_id=task_id,
            source=source,
            requirement_summary=requirement_summary,
            project_path=project_path,
            status=status,
            llm_wiki_refs=llm_wiki_refs,
            human_decisions=human_decisions,
            phase=phase,
            task_session=task_session,
            merge_records=merge_records,
            task_kind=task_kind,
            root_task_id=root_task_id,
            parent_task_id=parent_task_id,
            dependency_task_ids=dependency_task_ids,
            source_branch=source_branch,
            branch_policy=branch_policy,
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self.task_repository.get_task(task_id)

    def list_recent_tasks(
        self,
        *,
        statuses: list[str] | set[str] | tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.task_repository.list_recent_tasks(statuses=statuses, limit=limit)

    def list_child_tasks(self, parent_task_id: str) -> list[dict[str, Any]]:
        return self.task_repository.list_child_tasks(parent_task_id)

    def list_root_tasks(self, root_task_id: str) -> list[dict[str, Any]]:
        return self.task_repository.list_root_tasks(root_task_id)

    def update_status(self, task_id: str, status: str) -> None:
        self.task_repository.update_status(task_id, status)

    def update_phase(self, task_id: str, phase: str) -> None:
        self.task_repository.update_phase(task_id, phase)

    def update_task_session(self, task_id: str, updates: dict[str, Any]) -> None:
        self.task_repository.update_task_session(task_id, updates)

    def append_merge_record(self, task_id: str, record: dict[str, Any]) -> None:
        self.task_repository.append_merge_record(task_id, record)

    def update_requirement_summary(self, task_id: str, requirement_summary: str) -> None:
        self.task_repository.update_requirement_summary(task_id, requirement_summary)

    def update_task_hierarchy(
        self,
        task_id: str,
        *,
        task_kind: str | None = None,
        root_task_id: str | None = None,
        parent_task_id: str | None = None,
        dependency_task_ids: list[str] | None = None,
    ) -> None:
        self.task_repository.update_task_hierarchy(
            task_id,
            task_kind=task_kind,
            root_task_id=root_task_id,
            parent_task_id=parent_task_id,
            dependency_task_ids=dependency_task_ids,
        )

    def update_source_context(self, task_id: str, source_context: dict[str, Any]) -> None:
        self.task_repository.update_source_context(task_id, source_context)

    def update_project_context(
        self,
        task_id: str,
        *,
        project_name: str,
        project_path: str,
        confidence: float,
        match_evidence: list[dict[str, Any]],
    ) -> None:
        self.task_repository.update_project_context(
            task_id,
            project_name=project_name,
            project_path=project_path,
            confidence=confidence,
            match_evidence=match_evidence,
        )

    def replace_llm_wiki_refs(self, task_id: str, refs: list[dict[str, Any]]) -> None:
        self.task_repository.replace_llm_wiki_refs(task_id, refs)

    def append_agent_run(self, task_id: str, run: dict[str, Any]) -> None:
        self.run_repository.append_agent_run(task_id, run)

    def upsert_agent_run(self, task_id: str, run: dict[str, Any]) -> None:
        self.run_repository.upsert_agent_run(task_id, run)

    def append_artifact(self, task_id: str, artifact: dict[str, Any]) -> None:
        self.artifact_repository.append_artifact(task_id, artifact)

    def upsert_artifact(self, task_id: str, artifact: dict[str, Any]) -> None:
        self.artifact_repository.upsert_artifact(task_id, artifact)

    def append_human_decision(self, task_id: str, decision: dict[str, Any]) -> None:
        self.task_repository.append_human_decision(task_id, decision)

    def mark_cancelled(self, task_or_run_id: str) -> bool:
        return self.task_repository.mark_cancelled(task_or_run_id)

    def delete_task(self, task_id: str) -> bool:
        deleted = self.task_repository.delete_task(task_id)
        self.binding_repository.delete_active_bindings_for_task(task_id)
        return deleted

    def bind_active_task(self, *, binding_key: str, task_id: str, scope: dict[str, Any]) -> None:
        self.binding_repository.bind_active_task(binding_key=binding_key, task_id=task_id, scope=scope)

    def get_active_binding(self, binding_key: str) -> dict[str, Any] | None:
        return self.binding_repository.get_active_binding(binding_key)

    def clear_active_binding(self, binding_key: str) -> bool:
        return self.binding_repository.clear_active_binding(binding_key)

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
        self.binding_repository.upsert_project_workitem_binding(
            identity=identity,
            hermes_task_id=hermes_task_id,
            relation_kind=relation_kind,
            source_workitem_key=source_workitem_key,
            root_task_id=root_task_id,
            parent_task_id=parent_task_id,
            external_status=external_status,
            writeback_status=writeback_status,
            metadata=metadata,
        )

    def find_task_by_project_workitem(self, project_workitem_key: str) -> dict[str, Any] | None:
        binding = self.find_project_workitem_binding(project_workitem_key)
        if binding is None:
            return None
        return self.get_task(binding["hermes_task_id"])

    def find_task_by_project_workitem_url(self, url: str) -> dict[str, Any] | None:
        task_id = self.binding_repository.find_task_id_by_project_workitem_url(url)
        return self.get_task(task_id) if task_id else None

    def find_project_workitem_binding(self, project_workitem_key: str) -> dict[str, Any] | None:
        return self.binding_repository.find_project_workitem_binding(project_workitem_key)

    def list_project_workitem_bindings(self, task_id: str) -> list[dict[str, Any]]:
        return self.binding_repository.list_project_workitem_bindings(task_id)
