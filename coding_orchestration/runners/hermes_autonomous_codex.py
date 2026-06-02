from __future__ import annotations

import json
from pathlib import Path

from ..codex_reuse import CodexReuseStrategy
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
        decision = CodexReuseStrategy(
            hermes_runtime_available=True,
            codex_cli_available=True,
            hermes_codex_provider_available=True,
            codex_cli_auth_available=True,
        ).select_backend(mode="implementation")
        metadata = {
            "runner": self.name,
            "backend": decision.backend,
            "hermes_provider": decision.hermes_provider,
            "requires_pty": decision.requires_pty,
            "uses_process_tool": decision.uses_process_tool,
            "must_not_copy_codex_auth_json": decision.must_not_copy_codex_auth_json,
            "auth_notes": decision.auth_notes,
            "hermes_skill": "autonomous-ai-agents/codex",
            "skill_path": self.skill_path,
            "notes": [
                "Hermes autonomous-ai-agents/codex is an agent-facing terminal/process workflow.",
                "Codex CLI workspace edits should run through Hermes terminal/process with pty=true and background process polling when available.",
                "Hermes openai-codex provider/OAuth is model capability backed by ~/.hermes/auth.json, not standalone Codex CLI auth.",
                "Standalone Codex CLI may use ~/.codex/auth.json; do not copy or auto-import it into ~/.hermes/auth.json.",
                "This runner preserves Task Ledger, manifest, report fallback, checkpoint commits, and diff guard.",
                "Fallback to direct Codex subprocess remains only for old Hermes environments without terminal/process dispatch.",
            ],
        }
        (run_dir / "autonomous-codex-backend.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
