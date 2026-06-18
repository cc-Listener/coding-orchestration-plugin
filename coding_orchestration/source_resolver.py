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
from .ports import SourceResult


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
SHEET_READ_SCOPE_ALIASES = (
    "sheets:spreadsheet:read",
    "sheets:spreadsheet:readonly",
    "sheets:spreadsheet.meta:read",
)
SHEET_READ_SCOPE_DISPLAY = "sheets:spreadsheet:readonly or sheets:spreadsheet.meta:read"


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
        result = self.resolve_source_result(args, gateway=gateway)
        return result.context or None

    def resolve_source_result(self, args: dict[str, Any] | None = None, gateway: Any = None) -> SourceResult:
        return SourceResult.from_context(self._resolve_source_context(args, gateway=gateway))

    def _resolve_source_context(self, args: dict[str, Any] | None = None, gateway: Any = None) -> dict[str, Any] | None:
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
            result = runner(["rtk", "lark-cli", "auth", "status", "--verify"])
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

        auth_payload = self._extract_lark_json(output)
        user_payload = self._lark_user_payload(auth_payload)
        needs_refresh = self._lark_needs_refresh(output, user_payload)
        verified = self._lark_auth_verified(auth_payload, user_payload)
        has_docx = "docx:document:readonly" in output
        has_wiki = "wiki:node:read" in output or "wiki:node:retrieve" in output
        has_sheets = any(scope in output for scope in SHEET_READ_SCOPE_ALIASES)
        if needs_refresh and not verified:
            return {
                "ok": False,
                "status": "auth_needed",
                "needs_refresh": True,
                "missing_scopes": [],
                "error": "lark-cli user identity needs_refresh",
                "recovery_action": (
                    "当前 lark-cli user token 已过期或需要刷新。请在同一终端用户下重新授权："
                    'rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read '
                    'wiki:node:retrieve sheets:spreadsheet:read"；完成授权后重新执行安装脚本。'
                ),
                "raw": output,
                "expected_app_id": expected_app_id,
                "actual_app_id": actual_app_id,
            }

        verify_problem = self._lark_verify_problem(auth_payload, user_payload)
        if verify_problem:
            error = self._lark_verify_error(auth_payload, user_payload, verify_problem)
            return {
                "ok": False,
                "status": "verify_failed",
                "needs_refresh": False,
                "missing_scopes": [],
                "error": error,
                "recovery_action": self._lark_verify_recovery(error),
                "raw": output,
                "expected_app_id": expected_app_id,
                "actual_app_id": actual_app_id,
            }

        missing = []
        if not has_docx:
            missing.append("docx:document:readonly")
        if not has_wiki:
            missing.append("wiki:node:read or wiki:node:retrieve")
        if args.get("require_sheets_scope") and not has_sheets:
            missing.append(SHEET_READ_SCOPE_DISPLAY)
        if missing:
            return {
                "ok": False,
                "status": "permission_missing",
                "needs_refresh": False,
                "missing_scopes": missing,
                "error": f"missing lark scopes: {', '.join(missing)}",
                "recovery_action": (
                    "请为当前 lark-cli app 补充缺失 scope："
                    f'rtk lark-cli auth login --scope "{self._scope_login_hint(missing)}"；'
                    "完成授权后重新执行安装脚本。"
                ),
                "raw": output,
                "expected_app_id": expected_app_id,
                "actual_app_id": actual_app_id,
            }

        return {
            "ok": True,
            "status": "ok",
            "needs_refresh": needs_refresh,
            "missing_scopes": [],
            "error": "",
            "recovery_action": "",
            "warning": (
                "lark-cli user tokenStatus=needs_refresh，但 --verify 已确认可自动刷新。"
                if needs_refresh
                else ""
            ),
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
    def _scope_login_hint(missing: list[str]) -> str:
        scopes: list[str] = []
        for item in missing:
            if item == "wiki:node:read or wiki:node:retrieve":
                scopes.extend(["wiki:node:read", "wiki:node:retrieve"])
            elif item == SHEET_READ_SCOPE_DISPLAY:
                scopes.append("sheets:spreadsheet:read")
            else:
                scopes.append(item)
        seen: set[str] = set()
        unique: list[str] = []
        for scope in scopes:
            if scope not in seen:
                seen.add(scope)
                unique.append(scope)
        return " ".join(unique)

    @staticmethod
    def _extract_lark_app_id(output: str) -> str:
        text = output or ""
        payload = SourceResolver._extract_lark_json(text)
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
    def _extract_lark_json(output: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", output or "", flags=re.S)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _lark_user_payload(payload: dict[str, Any]) -> dict[str, Any]:
        identities = payload.get("identities") if isinstance(payload, dict) else {}
        user = identities.get("user") if isinstance(identities, dict) else {}
        return user if isinstance(user, dict) else {}

    @staticmethod
    def _lark_needs_refresh(output: str, user_payload: dict[str, Any]) -> bool:
        token_status = str(user_payload.get("tokenStatus") or user_payload.get("token_status") or "").strip()
        user_status = str(user_payload.get("status") or "").strip()
        return token_status == "needs_refresh" or user_status == "needs_refresh" or "needs_refresh" in (output or "")

    @staticmethod
    def _lark_auth_verified(payload: dict[str, Any], user_payload: dict[str, Any]) -> bool:
        return bool(payload.get("verified")) or bool(user_payload.get("verified"))

    @staticmethod
    def _lark_verify_problem(payload: dict[str, Any], user_payload: dict[str, Any]) -> str:
        if not payload or not user_payload:
            return ""
        user_status = str(user_payload.get("status") or "").strip()
        identity = str(payload.get("identity") or "").strip()
        if user_status == "verify_failed":
            return user_status
        if user_payload.get("available") is False:
            return user_status or "unavailable"
        if user_payload.get("verified") is False or payload.get("verified") is False:
            return user_status or "verify_failed"
        user_is_usable = user_payload.get("available") is True or user_payload.get("verified") is True
        if identity == "none" and not user_is_usable:
            return user_status or "no_usable_identity"
        return ""

    @staticmethod
    def _lark_verify_error(payload: dict[str, Any], user_payload: dict[str, Any], problem: str) -> str:
        message = (
            str(user_payload.get("message") or "").strip()
            or str(payload.get("note") or "").strip()
            or str(user_payload.get("hint") or "").strip()
        )
        message = message.replace("`lark-cli ", "`rtk lark-cli ").replace("run: lark-cli ", "run: rtk lark-cli ")
        label_by_problem = {
            "verify_failed": "lark-cli 用户身份校验失败（verify_failed）",
            "no_usable_identity": "lark-cli 当前没有可用用户身份",
            "unavailable": "lark-cli 用户身份不可用",
        }
        label = label_by_problem.get(problem, f"lark-cli 用户身份不可用（{problem}）")
        if message:
            return f"{label}：{message}"
        return label

    @staticmethod
    def _lark_verify_recovery(error: str) -> str:
        lowered = error.lower()
        if any(marker in lowered for marker in ("no such host", "dial tcp", "timeout", "network")):
            return "请先修复当前终端访问 open.feishu.cn 的网络、DNS 或代理问题。"
        return (
            "请重新执行 lark-cli 用户授权："
            'rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read '
            'wiki:node:retrieve sheets:spreadsheet:read"。'
        )

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
