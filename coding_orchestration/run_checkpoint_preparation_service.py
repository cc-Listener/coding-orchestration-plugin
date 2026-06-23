from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .run.projections import run_start_selection_projection
from .run.projections.run_start_selection_projection import RunManifestCheckpointPreparation

CheckpointPreparationCallback = Callable[[Path | None, str], dict[str, str] | None]


@dataclass(frozen=True)
class RunCheckpointPreparationResult:
    manifest_updates: dict[str, Any]


def prepare_run_checkpoint(
    *,
    checkpoint_preparation: RunManifestCheckpointPreparation,
    workspace_path: Path | None,
    task_id: str,
    prepare_qa_checkpoint_callback: CheckpointPreparationCallback,
    prepare_merge_test_checkpoint_callback: CheckpointPreparationCallback,
) -> RunCheckpointPreparationResult:
    checkpoint_payload: dict[str, str] | None = None
    if (
        checkpoint_preparation.checkpoint_kind
        == run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_QA
    ):
        checkpoint_payload = prepare_qa_checkpoint_callback(workspace_path, task_id)
    elif (
        checkpoint_preparation.checkpoint_kind
        == run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_MERGE_TEST
    ):
        checkpoint_payload = prepare_merge_test_checkpoint_callback(workspace_path, task_id)
    manifest_updates: dict[str, Any] = {}
    if checkpoint_payload is not None and checkpoint_preparation.manifest_field:
        manifest_updates[checkpoint_preparation.manifest_field] = checkpoint_payload
    return RunCheckpointPreparationResult(manifest_updates=manifest_updates)
