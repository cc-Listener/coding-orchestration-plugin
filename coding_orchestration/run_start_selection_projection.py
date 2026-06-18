from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import RunMode, TaskPhase


@dataclass(frozen=True)
class RunWorkspaceSelection:
    workspace_kind: str
    preparation_phase: TaskPhase | None = None
    missing_workspace_reason: str = ""


RUN_CONTEXT_SOURCE_CONFIRMED_PLAN = "confirmed_plan"
RUN_CONTEXT_SOURCE_MERGE_TEST_CONTEXT = "merge_test_context"
RUN_MANIFEST_CHECKPOINT_NONE = "none"
RUN_MANIFEST_CHECKPOINT_QA = "qa"
RUN_MANIFEST_CHECKPOINT_MERGE_TEST = "merge_test"
RUN_WORKSPACE_NONE = "none"
RUN_WORKSPACE_CREATE_IMPLEMENTATION = "create_implementation"
RUN_WORKSPACE_EXISTING_IMPLEMENTATION = "existing_implementation"


@dataclass(frozen=True)
class RunManifestCheckpointPreparation:
    checkpoint_kind: str
    manifest_field: str = ""
    target_branch: str = ""


def run_context_source_for_mode(mode: RunMode) -> str:
    if mode == RunMode.IMPLEMENTATION:
        return RUN_CONTEXT_SOURCE_CONFIRMED_PLAN
    if mode in {RunMode.QA, RunMode.MERGE_TEST}:
        return RUN_CONTEXT_SOURCE_MERGE_TEST_CONTEXT
    return ""


def run_checkpoint_for_mode(
    *,
    mode: RunMode,
    qa_checkpoint: Any,
    merge_test_checkpoint: Any,
) -> Any:
    if mode == RunMode.QA:
        return qa_checkpoint
    if mode == RunMode.MERGE_TEST:
        return merge_test_checkpoint
    return None


def run_checkpoint_failed(checkpoint: Any) -> bool:
    return isinstance(checkpoint, dict) and checkpoint.get("status") == "failed"


def run_observes_qa_evidence(mode: RunMode) -> bool:
    return mode == RunMode.QA


def run_records_source_branch(mode: RunMode) -> bool:
    return mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}


def run_requires_project_path(mode: RunMode) -> bool:
    return mode != RunMode.DECOMPOSITION


def run_workspace_selection_for_mode(mode: RunMode) -> RunWorkspaceSelection:
    if mode == RunMode.IMPLEMENTATION:
        return RunWorkspaceSelection(
            workspace_kind=RUN_WORKSPACE_CREATE_IMPLEMENTATION,
            preparation_phase=TaskPhase.GITOPS_PREPARING,
        )
    if mode == RunMode.QA:
        return RunWorkspaceSelection(
            workspace_kind=RUN_WORKSPACE_EXISTING_IMPLEMENTATION,
            missing_workspace_reason="task has no implementation worktree to QA",
        )
    if mode == RunMode.MERGE_TEST:
        return RunWorkspaceSelection(
            workspace_kind=RUN_WORKSPACE_EXISTING_IMPLEMENTATION,
            missing_workspace_reason="task has no implementation worktree to merge from",
        )
    return RunWorkspaceSelection(workspace_kind=RUN_WORKSPACE_NONE)


def run_manifest_checkpoint_preparation_for_mode(mode: RunMode) -> RunManifestCheckpointPreparation:
    if mode == RunMode.QA:
        return RunManifestCheckpointPreparation(
            checkpoint_kind=RUN_MANIFEST_CHECKPOINT_QA,
            manifest_field="qa_checkpoint",
        )
    if mode == RunMode.MERGE_TEST:
        return RunManifestCheckpointPreparation(
            checkpoint_kind=RUN_MANIFEST_CHECKPOINT_MERGE_TEST,
            manifest_field="merge_test_checkpoint",
            target_branch="test",
        )
    return RunManifestCheckpointPreparation(checkpoint_kind=RUN_MANIFEST_CHECKPOINT_NONE)
