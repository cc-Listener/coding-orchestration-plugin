from __future__ import annotations

import os
from typing import Any

from .codex_reuse import CodexReuseStrategy
from ..models import RunMode
from .codex_cli import CodexCliRunner
from .generic_cli import GenericCliRunner
from .hermes_autonomous_codex import HermesAutonomousCodexRunner


class RunnerUnavailable(ValueError):
    pass


class RunnerRouter:
    def __init__(self, default_runner: str, runners: dict[str, Any], codex_reuse_strategy: CodexReuseStrategy | None = None):
        self.default_runner = default_runner
        self.runners = runners
        self.codex_reuse_strategy = codex_reuse_strategy or CodexReuseStrategy(
            hermes_runtime_available=False,
            codex_cli_available=True,
            hermes_codex_provider_available=False,
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RunnerRouter":
        default_runner = str(config.get("default_runner") or "codex_cli")
        runners_cfg = config.get("runners") or {}
        runners: dict[str, Any] = {
            "codex_cli": CodexCliRunner(
                command=(runners_cfg.get("codex_cli") or {}).get("command")
                or os.environ.get("CODEX_CLI_COMMAND")
                or "codex"
            ),
            "hermes_autonomous_codex": HermesAutonomousCodexRunner(
                command=(runners_cfg.get("hermes_autonomous_codex") or {}).get("command")
                or os.environ.get("HERMES_AUTONOMOUS_CODEX_COMMAND")
                or os.environ.get("CODEX_CLI_COMMAND")
                or "codex",
                skill_path=(runners_cfg.get("hermes_autonomous_codex") or {}).get("skill_path")
                or os.environ.get("HERMES_AUTONOMOUS_CODEX_SKILL")
                or "/Users/xiaojing/.hermes/hermes-agent/skills/autonomous-ai-agents/codex/SKILL.md",
            ),
        }
        if (runners_cfg.get("claude_code") or {}).get("enabled"):
            runners["claude_code"] = GenericCliRunner(
                name="claude_code",
                command=(runners_cfg.get("claude_code") or {}).get("command", "claude"),
            )
        if (runners_cfg.get("gemini") or {}).get("enabled"):
            runners["gemini"] = GenericCliRunner(
                name="gemini",
                command=(runners_cfg.get("gemini") or {}).get("command", "gemini"),
            )
        codex_reuse_strategy = CodexReuseStrategy(
            hermes_runtime_available=bool(config.get("hermes_runtime_available") or config.get("dispatch_tool")),
            codex_cli_available=bool(config.get("codex_cli_available", True)),
            hermes_codex_provider_available=bool(
                config.get("hermes_codex_provider_available")
                or os.environ.get("HERMES_OPENAI_CODEX_PROVIDER") == "1"
            ),
            codex_cli_auth_available=bool(
                config.get("codex_cli_auth_available")
                or os.environ.get("CODEX_CLI_AUTH_AVAILABLE") == "1"
            ),
        )
        return cls(default_runner=default_runner, runners=runners, codex_reuse_strategy=codex_reuse_strategy)

    def codex_backend_decision(self, mode: RunMode | str):
        mode_value = mode.value if isinstance(mode, RunMode) else str(mode)
        return self.codex_reuse_strategy.select_backend(mode=mode_value)

    def set_hermes_runtime(self, hermes_runtime: Any) -> None:
        for runner in self.runners.values():
            if hasattr(runner, "set_hermes_runtime"):
                runner.set_hermes_runtime(hermes_runtime)
        self.codex_reuse_strategy = CodexReuseStrategy(
            hermes_runtime_available=bool(hermes_runtime and hermes_runtime.available()),
            codex_cli_available=True,
            hermes_codex_provider_available=self.codex_reuse_strategy.hermes_codex_provider_available,
            codex_cli_auth_available=self.codex_reuse_strategy.codex_cli_auth_available,
        )

    def select_runner(self, mode: RunMode, requested: str | None = None):
        name = requested or self.default_runner
        runner = self.runners.get(name)
        if runner is None:
            raise RunnerUnavailable(f"runner is not enabled: {name}")
        caps = runner.capabilities()
        if mode == RunMode.PLAN_ONLY and not caps.supports_plan_only:
            raise RunnerUnavailable(f"runner does not support plan-only: {name}")
        if mode == RunMode.IMPLEMENTATION and not caps.supports_implementation:
            raise RunnerUnavailable(f"runner does not support implementation: {name}")
        return runner
