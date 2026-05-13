from __future__ import annotations

from pathlib import Path

from .base import CodingAgentRunner
from ..models import ArtifactSet, RunnerCapabilities


class GenericCliRunner(CodingAgentRunner):
    def __init__(self, name: str, command: str):
        self.name = name
        self.command = command

    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(
            supports_plan_only=True,
            supports_implementation=True,
            supports_streaming_events=False,
            supports_cancel=True,
            supports_resume=False,
            supports_app_server=False,
            supports_structured_output=False,
            output_format="freetext",
            sandbox_level="external_workspace",
        )

    def cancel(self, run_id: str) -> bool:
        return False

    def collect_artifacts(self, run_dir: Path) -> ArtifactSet:
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
        )
