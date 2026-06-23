from __future__ import annotations

from dataclasses import dataclass


CODEX_AUTH_NOTES = (
    "Hermes openai-codex provider uses ~/.hermes/auth.json. "
    "Standalone Codex CLI may use ~/.codex/auth.json. "
    "Do not copy or auto-import ~/.codex/auth.json into Hermes because Codex OAuth refresh tokens are single-use."
)


@dataclass(frozen=True)
class CodexBackendDecision:
    backend: str
    hermes_provider: str
    requires_pty: bool
    uses_process_tool: bool
    must_not_copy_codex_auth_json: bool
    auth_notes: str


@dataclass(frozen=True)
class CodexReuseStrategy:
    hermes_runtime_available: bool
    codex_cli_available: bool
    hermes_codex_provider_available: bool
    codex_cli_auth_available: bool = False

    def select_backend(self, mode: str) -> CodexBackendDecision:
        if self.hermes_runtime_available and self.codex_cli_available:
            return CodexBackendDecision(
                backend="hermes_terminal_codex_cli",
                hermes_provider="openai-codex" if self.hermes_codex_provider_available else "",
                requires_pty=True,
                uses_process_tool=True,
                must_not_copy_codex_auth_json=True,
                auth_notes=CODEX_AUTH_NOTES,
            )
        if self.hermes_codex_provider_available:
            return CodexBackendDecision(
                backend="hermes_openai_codex_provider",
                hermes_provider="openai-codex",
                requires_pty=False,
                uses_process_tool=False,
                must_not_copy_codex_auth_json=True,
                auth_notes=CODEX_AUTH_NOTES,
            )
        return CodexBackendDecision(
            backend="direct_codex_cli_fallback",
            hermes_provider="",
            requires_pty=True,
            uses_process_tool=False,
            must_not_copy_codex_auth_json=True,
            auth_notes=CODEX_AUTH_NOTES,
        )
