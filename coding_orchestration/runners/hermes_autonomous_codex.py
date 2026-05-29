from __future__ import annotations

import json
from pathlib import Path

from ..models import RunnerCapabilities
from .codex_cli import CodexCliRunner


class HermesAutonomousCodexRunner(CodexCliRunner):
    """Codex runner profile aligned with Hermes' autonomous-ai-agents/codex skill.

    The Hermes bundled skill is an agent-facing terminal/process workflow, not a
    plugin-callable Python API. This runner keeps the coding orchestration
    contracts intact while isolating the execution backend so it can later swap
    from direct Codex CLI subprocesses to Hermes terminal/process primitives.
    """

    name = "hermes_autonomous_codex"

    def __init__(
        self,
        command: str = "codex",
        skill_path: str | Path = "/Users/xiaojing/.hermes/hermes-agent/skills/autonomous-ai-agents/codex/SKILL.md",
    ):
        super().__init__(command=command)
        self.skill_path = str(Path(skill_path).expanduser())

    def capabilities(self) -> RunnerCapabilities:
        caps = super().capabilities()
        return RunnerCapabilities(
            supports_plan_only=caps.supports_plan_only,
            supports_implementation=caps.supports_implementation,
            supports_streaming_events=caps.supports_streaming_events,
            supports_cancel=caps.supports_cancel,
            supports_resume=caps.supports_resume,
            supports_app_server=caps.supports_app_server,
            supports_structured_output=caps.supports_structured_output,
            output_format=caps.output_format,
            sandbox_level="hermes_autonomous_codex",
        )

    def run(self, **kwargs):
        run_dir = kwargs["run_dir"]
        self._write_backend_metadata(run_dir)
        return super().run(**kwargs)

    def _write_backend_metadata(self, run_dir: Path) -> None:
        metadata = {
            "runner": self.name,
            "backend": "direct_codex_cli",
            "hermes_skill": "autonomous-ai-agents/codex",
            "skill_path": self.skill_path,
            "notes": [
                "Hermes autonomous-ai-agents/codex is currently an agent-facing skill, not a plugin-callable API.",
                "This runner preserves Task Ledger, manifest, report fallback, checkpoint commits, and diff guard.",
                "The direct Codex subprocess can later be replaced by Hermes terminal/process primitives behind this runner.",
            ],
        }
        (run_dir / "autonomous-codex-backend.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
