from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ...models import RunMode
from ...runners.base import RunResult


def dispatch_run(
    *,
    runner: Any,
    run_id: str,
    run_dir: Path,
    project_path: Path,
    workspace_path: Path | None,
    mode: RunMode,
    timeout_seconds: int,
    checkpoint: dict[str, Any] | None,
    checkpoint_failed_callback: Callable[[dict[str, Any] | None], bool],
    checkpoint_failed_result_callback: Callable[..., RunResult],
    runner_failed_result_callback: Callable[..., RunResult],
) -> RunResult:
    if checkpoint_failed_callback(checkpoint):
        return checkpoint_failed_result_callback(
            runner_name=runner.name,
            run_dir=run_dir,
            mode=mode,
            checkpoint=checkpoint or {},
        )
    try:
        return runner.run(
            run_id=run_id,
            run_dir=run_dir,
            project_path=project_path,
            workspace_path=workspace_path,
            mode=mode,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return runner_failed_result_callback(
            runner_name=runner.name,
            run_dir=run_dir,
            mode=mode,
            error=exc,
        )
