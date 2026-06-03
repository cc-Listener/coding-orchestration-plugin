from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
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
        args = args or {}
        runner = self.command_runner or self._run
        expected_app_id = self._expected_lark_app_id(args)
        config_result: subprocess.CompletedProcess[str] | None = None
        if expected_app_id:
            try:
                config_result = runner(["rtk", "lark-cli", "config", "show"])
            except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
                return {
                    "ok": False,
                    "status": "failed",
                    "needs_refresh": False,
                    "missing_scopes": [],
                    "error": f"lark-cli config show failed: {exc}",
                    "recovery_action": "Verify lark-cli is installed and available in the Hermes runtime PATH.",
                    "raw": "",
                    "expected_app_id": expected_app_id,
                    "actual_app_id": "",
                }
            config_output = "\n".join(filter(None, [config_result.stdout, config_result.stderr]))
            if config_result.returncode != 0:
                return {
                    "ok": False,
                    "status": "failed",
                    "needs_refresh": False,
                    "missing_scopes": [],
                    "error": f"lark-cli config show failed with exit_code={config_result.returncode}: {config_output}",
                    "recovery_action": "Run rtk lark-cli config show manually in the Hermes user context and fix the reported error.",
                    "raw": config_output,
                    "expected_app_id": expected_app_id,
                    "actual_app_id": "",
                }
            actual_app_id = self._extract_lark_app_id(config_output)
            if actual_app_id != expected_app_id:
                return {
                    "ok": False,
                    "status": "app_mismatch",
                    "needs_refresh": False,
                    "missing_scopes": [],
                    "error": (
                        "terminal default lark-cli appId does not match Hermes FEISHU_APP_ID: "
                        f"expected {expected_app_id}, got {actual_app_id or 'unknown'}"
                    ),
                    "recovery_action": (
                        "Make terminal lark-cli use the Hermes Feishu app, then authorize user scopes: "
                        "rtk lark-cli config bind --source hermes --identity user-default "
                        "or rtk lark-cli config init --app-id <FEISHU_APP_ID> --app-secret-stdin --brand feishu."
                    ),
                    "raw": config_output,
                    "expected_app_id": expected_app_id,
                    "actual_app_id": actual_app_id,
                }

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
                "expected_app_id": expected_app_id,
                "actual_app_id": self._extract_lark_app_id((config_result.stdout if config_result else "") or ""),
            }

        output = "\n".join(filter(None, [result.stdout, result.stderr]))
        actual_app_id = self._extract_lark_app_id((config_result.stdout if config_result else "") or output)
        if result.returncode != 0:
            return {
                "ok": False,
                "status": "failed",
                "needs_refresh": False,
                "missing_scopes": [],
                "error": f"lark-cli auth status failed with exit_code={result.returncode}: {output}",
                "recovery_action": "Run lark-cli auth status manually in the Hermes user context and fix the reported error.",
                "raw": output,
                "expected_app_id": expected_app_id,
                "actual_app_id": actual_app_id,
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
                "expected_app_id": expected_app_id,
                "actual_app_id": actual_app_id,
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
                "expected_app_id": expected_app_id,
                "actual_app_id": actual_app_id,
            }

        return {
            "ok": True,
            "status": "ok",
            "needs_refresh": False,
            "missing_scopes": [],
            "error": "",
            "recovery_action": "",
            "raw": output,
            "expected_app_id": expected_app_id,
            "actual_app_id": actual_app_id,
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

    @staticmethod
    def _extract_lark_app_id(output: str) -> str:
        text = output or ""
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                return str(payload.get("appId") or payload.get("app_id") or "").strip()
        patterns = (
            r'"appId"\s*:\s*"([^"]+)"',
            r"\bappId\s*[:=]\s*([A-Za-z0-9_:-]+)",
            r"\bactive app\s*[:=]\s*([A-Za-z0-9_:-]+)",
        )
        for pattern in patterns:
            found = re.search(pattern, text)
            if found:
                return found.group(1).strip()
        return ""

    @staticmethod
    def _expected_lark_app_id(args: dict[str, Any]) -> str:
        explicit = str(args.get("expected_app_id") or args.get("feishu_app_id") or "").strip()
        if explicit:
            return explicit
        env_value = os.getenv("FEISHU_APP_ID", "").strip()
        if env_value:
            return env_value
        hermes_home = Path(str(args.get("hermes_home") or os.getenv("HERMES_HOME") or Path.home() / ".hermes")).expanduser()
        env_path = hermes_home / ".env"
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == "FEISHU_APP_ID":
                return value.strip().strip('"').strip("'")
        return ""
