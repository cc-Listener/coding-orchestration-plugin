from __future__ import annotations

from pathlib import Path
from typing import Any

from . import workspace_checkpoint_service


class OrchestratorWorkspaceFacadeMixin:
    def _implementation_workspace(self, task: dict[str, Any], project_path: Path, run_id: str) -> Path:
        return self.workspace_checkpoint_service.implementation_workspace(task, project_path, run_id)

    def _merge_test_workspace(self, task: dict[str, Any]) -> Path | None:
        return self.workspace_checkpoint_service.merge_test_workspace(task)

    @staticmethod
    def _collect_qa_artifacts(workspace_path: Path | None) -> dict[str, str]:
        return workspace_checkpoint_service.collect_qa_artifacts(workspace_path)

    @staticmethod
    def _prepare_qa_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
        return workspace_checkpoint_service.prepare_qa_checkpoint(workspace_path, task_id)

    @staticmethod
    def _prepare_merge_test_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
        return workspace_checkpoint_service.prepare_merge_test_checkpoint(workspace_path, task_id)

    @staticmethod
    def _workspace_has_uncommitted_changes(workspace_path: Path | None) -> bool:
        return workspace_checkpoint_service.workspace_has_uncommitted_changes(workspace_path)

    @staticmethod
    def _workspace_clean_checkpoint(workspace_path: Path | None) -> dict[str, str]:
        return workspace_checkpoint_service.workspace_clean_checkpoint(workspace_path)

    @staticmethod
    def _git_head(workspace_path: Path | None) -> str:
        return workspace_checkpoint_service.git_head(workspace_path)

    @staticmethod
    def _source_branch_for_task(task: dict[str, Any], project_name: str) -> str:
        return workspace_checkpoint_service.source_branch_for_task(task, project_name)

    @staticmethod
    def _source_base_branch_for_task(task: dict[str, Any]) -> str:
        return workspace_checkpoint_service.source_base_branch_for_task(task)

    @staticmethod
    def _task_short_id(task_id: str) -> str:
        return workspace_checkpoint_service.task_short_id(task_id)

    @staticmethod
    def _slugify_ascii(text: str) -> str:
        return workspace_checkpoint_service.slugify_ascii(text)

    @staticmethod
    def _latest_existing_implementation_workspace(task: dict[str, Any]) -> Path | None:
        return workspace_checkpoint_service.latest_existing_implementation_workspace(task)
