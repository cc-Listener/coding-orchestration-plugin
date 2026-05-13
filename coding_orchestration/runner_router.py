from __future__ import annotations

import os
from typing import Any

from .models import RunMode
from .runners.codex_cli import CodexCliRunner
from .runners.generic_cli import GenericCliRunner


class RunnerUnavailable(ValueError):
    pass


class RunnerRouter:
    def __init__(self, default_runner: str, runners: dict[str, Any]):
        self.default_runner = default_runner
        self.runners = runners

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RunnerRouter":
        default_runner = str(config.get("default_runner") or "codex_cli")
        runners_cfg = config.get("runners") or {}
        runners: dict[str, Any] = {
            "codex_cli": CodexCliRunner(
                command=(runners_cfg.get("codex_cli") or {}).get("command")
                or os.environ.get("CODEX_CLI_COMMAND")
                or "codex"
            )
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
        return cls(default_runner=default_runner, runners=runners)

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
