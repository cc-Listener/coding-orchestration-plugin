from __future__ import annotations

from pathlib import Path

from ..models import ArtifactSet


def collect_codex_artifacts(run_dir: Path) -> ArtifactSet:
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
