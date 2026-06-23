from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import ArtifactSet


def artifact_set_for_run_dir(run_dir: Path) -> ArtifactSet:
    return ArtifactSet(
        run_dir=run_dir,
        input_prompt=run_dir / "input-prompt.md",
        manifest=run_dir / "run-manifest.json",
        stdout=run_dir / "stdout.log",
        stderr=run_dir / "stderr.log",
        events=run_dir / "events.jsonl",
        report=run_dir / "report.json",
        summary=run_dir / "summary.md",
        diff=run_dir / "diff.patch",
        operator_log=run_dir / "run-log.md",
        execution_policy=run_dir / "execution-policy.json",
        context_manifest=run_dir / "context-manifest.json",
    )


def artifact_set_for_existing_run(
    *,
    task_id: str,
    run_id: str,
    run: dict[str, Any],
    run_root: Path,
) -> ArtifactSet:
    artifact = run.get("artifact") or {}
    run_dir = Path(str(artifact.get("run_dir") or run_root / task_id / run_id)).expanduser()

    def artifact_path(key: str, filename: str) -> Path:
        return Path(str(artifact.get(key) or run_dir / filename)).expanduser()

    return ArtifactSet(
        run_dir=run_dir,
        input_prompt=artifact_path("input_prompt", "input-prompt.md"),
        manifest=artifact_path("manifest", "run-manifest.json"),
        stdout=artifact_path("stdout", "stdout.log"),
        stderr=artifact_path("stderr", "stderr.log"),
        events=artifact_path("events", "events.jsonl"),
        report=artifact_path("report", "report.json"),
        summary=artifact_path("summary", "summary.md"),
        diff=artifact_path("diff", "diff.patch"),
        operator_log=artifact_path("operator_log", "run-log.md"),
        execution_policy=artifact_path("execution_policy", "execution-policy.json"),
        context_manifest=artifact_path("context_manifest", "context-manifest.json"),
    )
