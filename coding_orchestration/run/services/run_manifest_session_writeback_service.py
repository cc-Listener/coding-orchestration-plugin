from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ...models import RunMode
from .run_manifest_service import build_manifest_session_fields

ManifestSessionMetadataWritebackCallback = Callable[..., None]


@dataclass(frozen=True)
class RunManifestSessionWritebackResult:
    manifest_updates: dict[str, str]
    metadata_written: bool


def _manifest_value(manifest: Any, field: str) -> Any:
    if isinstance(manifest, dict):
        return manifest.get(field)
    return getattr(manifest, field, None)


def _set_manifest_values(manifest: Any, updates: dict[str, str]) -> None:
    if isinstance(manifest, dict):
        manifest.update(updates)
        return
    for field, value in updates.items():
        setattr(manifest, field, value)


def write_run_manifest_session_metadata(
    *,
    session_id: str,
    runner_name: str,
    mode: RunMode | str | None,
    manifest: Any,
    manifest_path: Path,
    update_manifest_session_metadata_callback: ManifestSessionMetadataWritebackCallback,
) -> RunManifestSessionWritebackResult:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return RunManifestSessionWritebackResult(
            manifest_updates={},
            metadata_written=False,
        )

    manifest_updates = build_manifest_session_fields(
        session_id=normalized_session_id,
        runner_name=runner_name,
        mode=mode,
        dangerous_bypass=bool(_manifest_value(manifest, "dangerous_bypass")),
        existing_resume_session_id=_manifest_value(manifest, "resume_session_id"),
        existing_session_visibility=_manifest_value(manifest, "session_visibility"),
    )
    _set_manifest_values(manifest, manifest_updates)
    update_manifest_session_metadata_callback(
        manifest_path=manifest_path,
        session_id=normalized_session_id,
        runner_name=runner_name,
    )
    return RunManifestSessionWritebackResult(
        manifest_updates=manifest_updates,
        metadata_written=True,
    )
