from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

WorkspaceCheckpointCallback = Callable[[Path | None], dict[str, str]]
ManifestWriteCallback = Callable[..., str]


@dataclass(frozen=True)
class RunImplementationCheckpointResult:
    implementation_checkpoint: dict[str, str] | None
    manifest_artifact: str | None
    manifest_written: bool


def _set_implementation_checkpoint(manifest: Any, checkpoint: dict[str, str]) -> None:
    if isinstance(manifest, dict):
        manifest["implementation_checkpoint"] = checkpoint
        return
    setattr(manifest, "implementation_checkpoint", checkpoint)


def write_implementation_checkpoint_if_dirty(
    *,
    implementation_dirty: bool,
    workspace_path: Path | None,
    manifest: Any,
    manifest_path: Path,
    workspace_clean_checkpoint_callback: WorkspaceCheckpointCallback,
    write_manifest_artifact_callback: ManifestWriteCallback,
) -> RunImplementationCheckpointResult:
    if not implementation_dirty:
        return RunImplementationCheckpointResult(
            implementation_checkpoint=None,
            manifest_artifact=None,
            manifest_written=False,
        )

    checkpoint = workspace_clean_checkpoint_callback(workspace_path)
    _set_implementation_checkpoint(manifest, checkpoint)
    manifest_artifact = write_manifest_artifact_callback(
        manifest_path=manifest_path,
        manifest=manifest,
    )
    return RunImplementationCheckpointResult(
        implementation_checkpoint=checkpoint,
        manifest_artifact=manifest_artifact,
        manifest_written=True,
    )
