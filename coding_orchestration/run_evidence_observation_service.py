from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

QaArtifactsCallback = Callable[[Path | None], dict[str, str]]
GitHeadCallback = Callable[[Path | None], str]
WorkspaceDirtyCallback = Callable[[Path | None], bool]


@dataclass(frozen=True)
class RunQaEvidenceObservation:
    qa_artifacts: dict[str, str]
    tested_commit: str


def observe_run_qa_evidence(
    *,
    enabled: bool,
    workspace_path: Path | None,
    collect_qa_artifacts_callback: QaArtifactsCallback,
    git_head_callback: GitHeadCallback,
) -> RunQaEvidenceObservation:
    if not enabled:
        return RunQaEvidenceObservation(qa_artifacts={}, tested_commit="")
    return RunQaEvidenceObservation(
        qa_artifacts=collect_qa_artifacts_callback(workspace_path),
        tested_commit=git_head_callback(workspace_path),
    )


def observe_implementation_dirty_check(
    *,
    required: bool,
    workspace_path: Path | None,
    workspace_has_uncommitted_changes_callback: WorkspaceDirtyCallback,
) -> bool:
    if not required:
        return False
    return workspace_has_uncommitted_changes_callback(workspace_path)
