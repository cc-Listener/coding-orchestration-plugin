from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .feishu_project_reader import FeishuProjectReader
from .meegle_reader import MeegleReader


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass
class SourceResolver:
    command_runner: CommandRunner | None = None
    meegle_reader: Any | None = None
    feishu_reader: Any | None = None

    def __post_init__(self) -> None:
        if self.meegle_reader is None:
            self.meegle_reader = MeegleReader()
        if self.feishu_reader is None:
            self.feishu_reader = FeishuProjectReader()

    def resolve_source(self, args: dict[str, Any] | None = None, gateway: Any = None) -> dict[str, Any] | None:
        args = args or {}
        text = str(args.get("url") or args.get("text") or "").strip()
        if not text:
            return None
        if MeegleReader.extract_first_link(text):
            return self.meegle_reader.read_from_text(text, gateway=gateway)
        return self.feishu_reader.read_from_text(text, gateway=gateway)

    def preflight_lark(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        runner = self.command_runner or self._run
        try:
            result = runner(["rtk", "lark-cli", "auth", "status"])
        except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
            return {
                "ok": False,
                "status": "failed",
                "needs_refresh": False,
                "missing_scopes": [],
                "error": f"lark-cli auth status failed: {exc}",
                "recovery_action": "Verify lark-cli is installed and available in the Hermes runtime PATH.",
                "raw": "",
            }

        output = "\n".join(filter(None, [result.stdout, result.stderr]))
        if result.returncode != 0:
            return {
                "ok": False,
                "status": "failed",
                "needs_refresh": False,
                "missing_scopes": [],
                "error": f"lark-cli auth status failed with exit_code={result.returncode}: {output}",
                "recovery_action": "Run lark-cli auth status manually in the Hermes user context and fix the reported error.",
                "raw": output,
            }

        needs_refresh = "needs_refresh" in output
        has_docx = "docx:document:readonly" in output
        has_wiki = "wiki:node:read" in output or "wiki:node:retrieve" in output
        if needs_refresh:
            return {
                "ok": False,
                "status": "auth_needed",
                "needs_refresh": True,
                "missing_scopes": [],
                "error": "lark-cli user identity needs_refresh",
                "recovery_action": "Run lark-cli auth refresh/login in the Hermes user context, then retry coding_lark_preflight.",
                "raw": output,
            }

        missing = []
        if not has_docx:
            missing.append("docx:document:readonly")
        if not has_wiki:
            missing.append("wiki:node:read or wiki:node:retrieve")
        if missing:
            return {
                "ok": False,
                "status": "permission_missing",
                "needs_refresh": False,
                "missing_scopes": missing,
                "error": f"missing lark scopes: {', '.join(missing)}",
                "recovery_action": "Authorize the active lark-cli app with the missing scopes.",
                "raw": output,
            }

        return {
            "ok": True,
            "status": "ok",
            "needs_refresh": False,
            "missing_scopes": [],
            "error": "",
            "recovery_action": "",
            "raw": output,
        }

    def preflight_meegle(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        runner = self.command_runner or self._run
        command_prefix = shlex.split(os.getenv("MEEGLE_CLI", "rtk lark-cli"))
        command = [*command_prefix, "meegle", "--help"]
        try:
            result = runner(command)
        except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
            return {
                "ok": False,
                "status": "unavailable",
                "error": f"Meegle CLI preflight failed: {exc}",
                "recovery_action": "Configure MEEGLE_CLI or install lark-cli support for Meegle work-item reads in the Hermes user context.",
                "raw": "",
            }
        output = "\n".join(filter(None, [result.stdout, result.stderr]))
        if result.returncode != 0:
            return {
                "ok": False,
                "status": "unavailable",
                "error": f"Meegle CLI preflight failed with exit_code={result.returncode}: {output}",
                "recovery_action": "Configure MEEGLE_CLI or add lark-cli meegle work-item get support, then retry hermes coding source-resolve.",
                "raw": output,
            }
        return {
            "ok": True,
            "status": "ok",
            "error": "",
            "recovery_action": "",
            "raw": output,
        }

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
