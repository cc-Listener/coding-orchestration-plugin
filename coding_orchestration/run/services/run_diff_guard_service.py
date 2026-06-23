from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import run_orchestration_service
from ...models import RunMode
from ...workspace import checkpoint_service as workspace_checkpoint_service


@dataclass(frozen=True)
class RunDiffGuardObservation:
    changed_files: list[str]
    violations: list[str]


def snapshot_run_diff_guard(*, diff_guard: Any, execution_root: Path) -> dict[str, str]:
    return diff_guard.snapshot(execution_root)


def observe_run_diff_guard(
    *,
    diff_guard: Any,
    execution_root: Path,
    before_snapshot: dict[str, str],
    mode: RunMode,
    workflow: Any,
    diff_path: Path,
) -> RunDiffGuardObservation:
    changed_files = diff_guard.changed_files(execution_root, before_snapshot)
    diff_guard_changed_files = workspace_checkpoint_service.diff_guard_changed_files_for_mode(
        mode,
        changed_files,
    )
    violations = diff_guard.find_violations(
        changed_files=diff_guard_changed_files,
        allowed_paths=workflow.allowed_paths,
        forbidden_paths=workflow.forbidden_paths,
    )
    violations = run_orchestration_service.build_run_diff_guard_violations(
        mode=mode,
        violations=violations,
        changed_files=changed_files,
    )
    diff_guard.write_diff_summary(diff_path, changed_files, violations)
    return RunDiffGuardObservation(changed_files=changed_files, violations=violations)
