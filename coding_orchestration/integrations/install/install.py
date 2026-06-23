from __future__ import annotations

"""Hermes plugin install and uninstall integration helpers."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


LEGACY_PLUGIN_ENTRIES = (
    "coding-orchestration-plugin",
    "coding-orchestration",
    "coding_orchestration_prod",
    "coding_orchestration_test",
)
LEGACY_RUNTIME_DIRS = (
    "coding-orchestration-prod",
    "coding-orchestration-test",
)
CURRENT_PLUGIN_ENTRY = "coding_orchestration"
CURRENT_RUNTIME_DIR = "coding-orchestration"
REQUIRED_CODEX_EXEC_OPTIONS = (
    "--json",
    "--output-schema",
    "--output-last-message",
    "--sandbox",
    "--dangerously-bypass-approvals-and-sandbox",
    "-C",
)
REQUIRED_LARK_SCOPES = (
    "docx:document:readonly",
    "wiki:node:read or wiki:node:retrieve",
    "sheets:spreadsheet:readonly or sheets:spreadsheet.meta:read",
)

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class InstallPreflightCheck:
    name: str
    ok: bool
    status: str
    error: str = ""
    recovery_action: str = ""
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "error": self.error,
            "recovery_action": self.recovery_action,
            "details": self.details or {},
        }


@dataclass(frozen=True)
class UninstallAction:
    path: Path
    kind: str
    reason: str
    existed: bool
    removable: bool = True
    removed: bool = False


def compute_plugin_link(repo_root: Path, hermes_home: Path) -> tuple[Path, Path]:
    source = repo_root / "coding_orchestration"
    target = hermes_home / "plugins" / CURRENT_PLUGIN_ENTRY
    return source, target


def ensure_plugin_symlink(repo_root: Path, hermes_home: Path) -> Path:
    source, target = compute_plugin_link(repo_root=repo_root, hermes_home=hermes_home)
    if not source.is_dir():
        raise FileNotFoundError(f"plugin source does not exist: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_symlink() and target.resolve() == source.resolve():
            return target
        raise FileExistsError(f"plugin target already exists and is not the expected symlink: {target}")
    target.symlink_to(source, target_is_directory=True)
    return target


def install_from_current_repo(repo_root: Path | None = None, hermes_home: Path | None = None) -> Path:
    resolved_repo = (repo_root or Path.cwd()).resolve()
    resolved_hermes = (hermes_home or (Path.home() / ".hermes")).expanduser().resolve()
    return ensure_plugin_symlink(repo_root=resolved_repo, hermes_home=resolved_hermes)


def read_hermes_env(hermes_home: Path | None = None) -> dict[str, str]:
    resolved_hermes = (hermes_home or (Path.home() / ".hermes")).expanduser().resolve()
    env_path = resolved_hermes / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def read_hermes_feishu_app_id(hermes_home: Path | None = None) -> str:
    return read_hermes_env(hermes_home).get("FEISHU_APP_ID", "")


def _default_run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)


def _command_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(filter(None, [result.stdout, result.stderr]))


def _run_check(
    *,
    name: str,
    command: list[str],
    runner: CommandRunner,
    recovery_action: str,
    required_output: tuple[str, ...] = (),
) -> InstallPreflightCheck:
    try:
        result = runner(command)
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        return InstallPreflightCheck(
            name=name,
            ok=False,
            status="failed",
            error=f"{name} command failed: {exc}",
            recovery_action=recovery_action,
            details={"command": command},
        )
    output = _command_output(result)
    if result.returncode != 0:
        return InstallPreflightCheck(
            name=name,
            ok=False,
            status="failed",
            error=f"{name} failed with exit_code={result.returncode}: {output}",
            recovery_action=recovery_action,
            details={"command": command, "output": output},
        )
    missing = [token for token in required_output if token not in output]
    if missing:
        return InstallPreflightCheck(
            name=name,
            ok=False,
            status="missing_capability",
            error=f"{name} output is missing required capability tokens: {', '.join(missing)}",
            recovery_action=recovery_action,
            details={"command": command, "missing": missing, "output": output},
        )
    return InstallPreflightCheck(
        name=name,
        ok=True,
        status="ok",
        details={"command": command, "output": output},
    )


def _check_hermes_env(resolved_hermes: Path, env: dict[str, str]) -> list[InstallPreflightCheck]:
    checks: list[InstallPreflightCheck] = []
    env_path = resolved_hermes / ".env"
    required = {
        "FEISHU_APP_ID": "Configure Hermes Feishu App ID in ~/.hermes/.env.",
        "FEISHU_APP_SECRET": "Configure Hermes Feishu App Secret in ~/.hermes/.env.",
        "CODEX_CLI_COMMAND": "Set CODEX_CLI_COMMAND=/absolute/path/to/codex in ~/.hermes/.env.",
    }
    for key, recovery in required.items():
        value = env.get(key, "").strip()
        checks.append(
            InstallPreflightCheck(
                name=f"hermes_env.{key}",
                ok=bool(value),
                status="ok" if value else "missing",
                error="" if value else f"{key} is missing in {env_path}",
                recovery_action="" if value else recovery,
                details={"env_path": str(env_path)},
            )
        )
    return checks


def _check_codex_cli(env: dict[str, str], runner: CommandRunner) -> list[InstallPreflightCheck]:
    checks: list[InstallPreflightCheck] = []
    command_value = env.get("CODEX_CLI_COMMAND", "").strip()
    if not command_value:
        return checks
    codex_path = Path(command_value).expanduser()
    if not codex_path.is_absolute():
        checks.append(
            InstallPreflightCheck(
                name="codex.path",
                ok=False,
                status="not_absolute",
                error="CODEX_CLI_COMMAND must be an absolute path.",
                recovery_action="Run rtk which codex and write that absolute path to ~/.hermes/.env.",
                details={"value": command_value},
            )
        )
        return checks
    if not codex_path.exists() or not os.access(codex_path, os.X_OK):
        checks.append(
            InstallPreflightCheck(
                name="codex.path",
                ok=False,
                status="not_executable",
                error=f"CODEX_CLI_COMMAND is not executable: {codex_path}",
                recovery_action="Install/login Codex CLI, then set CODEX_CLI_COMMAND to the executable absolute path.",
                details={"value": command_value},
            )
        )
        return checks
    checks.append(
        InstallPreflightCheck(
            name="codex.path",
            ok=True,
            status="ok",
            details={"value": command_value},
        )
    )
    codex = str(codex_path)
    checks.append(
        _run_check(
            name="codex.version",
            command=[codex, "--version"],
            runner=runner,
            recovery_action="Verify Codex CLI is installed and runnable by the Hermes Gateway user.",
        )
    )
    checks.append(
        _run_check(
            name="codex.exec_help",
            command=[codex, "exec", "--help"],
            runner=runner,
            required_output=REQUIRED_CODEX_EXEC_OPTIONS,
            recovery_action="Upgrade Codex CLI to a version that supports the coding runner flags.",
        )
    )
    checks.append(
        _run_check(
            name="codex.exec_resume_help",
            command=[codex, "exec", "resume", "--help"],
            runner=runner,
            required_output=("--json", "--output-last-message"),
            recovery_action="Upgrade Codex CLI to a version that supports codex exec resume.",
        )
    )
    return checks


def _check_hermes_cli(runner: CommandRunner) -> list[InstallPreflightCheck]:
    return [
        _run_check(
            name="hermes.version",
            command=["rtk", "hermes", "--version"],
            runner=runner,
            recovery_action="Install Hermes CLI and ensure rtk hermes is available to the Gateway user.",
        ),
        _run_check(
            name="hermes.plugins_list",
            command=["rtk", "hermes", "plugins", "list"],
            runner=runner,
            recovery_action="Fix Hermes plugin discovery before installing coding_orchestration.",
        ),
        _run_check(
            name="hermes.gateway_status",
            command=["rtk", "hermes", "gateway", "status"],
            runner=runner,
            recovery_action="Start or repair Hermes Gateway, then rerun install preflight.",
        ),
    ]


def _check_legacy_components(resolved_hermes: Path) -> InstallPreflightCheck:
    legacy = [
        action
        for action in collect_uninstall_actions(hermes_home=resolved_hermes)
        if action.existed and action.removable
    ]
    if not legacy:
        return InstallPreflightCheck(
            name="hermes.legacy_components",
            ok=True,
            status="ok",
            details={"existing": []},
        )
    existing = [str(action.path) for action in legacy]
    return InstallPreflightCheck(
        name="hermes.legacy_components",
        ok=False,
        status="conflict",
        error=f"legacy Hermes coding plugin components exist: {', '.join(existing)}",
        recovery_action="Run rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes, review dry-run, then rerun with --execute.",
        details={"existing": existing},
    )


def _check_lark(
    *,
    resolved_hermes: Path,
    env: dict[str, str],
    runner: CommandRunner,
) -> InstallPreflightCheck:
    from ...source.source_resolver import SourceResolver

    result = SourceResolver(command_runner=runner).preflight_lark(
        {
            "expected_app_id": env.get("FEISHU_APP_ID", ""),
            "hermes_home": str(resolved_hermes),
            "require_sheets_scope": True,
        }
    )
    return InstallPreflightCheck(
        name="lark.preflight",
        ok=bool(result.get("ok")),
        status=str(result.get("status") or ("ok" if result.get("ok") else "failed")),
        error=str(result.get("error") or ""),
        recovery_action=str(result.get("recovery_action") or ""),
        details=result,
    )


def run_install_preflight(
    hermes_home: Path | None = None,
    *,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    resolved_hermes = (hermes_home or (Path.home() / ".hermes")).expanduser().resolve()
    env = read_hermes_env(resolved_hermes)
    runner = command_runner or _default_run
    checks: list[InstallPreflightCheck] = []
    checks.extend(_check_hermes_env(resolved_hermes, env))
    checks.extend(_check_hermes_cli(runner))
    checks.extend(_check_codex_cli(env, runner))
    checks.append(_check_legacy_components(resolved_hermes))
    checks.append(_check_lark(resolved_hermes=resolved_hermes, env=env, runner=runner))

    failed = [check for check in checks if not check.ok]
    lark_check = next((check for check in checks if check.name == "lark.preflight"), None)
    lark_details = lark_check.details if lark_check and isinstance(lark_check.details, dict) else {}
    first_failed = failed[0] if failed else None
    return {
        "ok": not failed,
        "status": "ok" if not failed else "failed",
        "checks": [check.as_dict() for check in checks],
        "error": first_failed.error if first_failed else "",
        "recovery_action": first_failed.recovery_action if first_failed else "",
        "expected_app_id": env.get("FEISHU_APP_ID", ""),
        "actual_app_id": str(lark_details.get("actual_app_id") or ""),
        "required_lark_scopes": list(REQUIRED_LARK_SCOPES),
    }


def _path_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.exists():
        return "file"
    return "missing"


def _ensure_child_path(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"refusing to remove path outside Hermes home: {path}") from exc


def _normalize_hermes_child_path(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded.parent.resolve(strict=False) / expanded.name


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)


def collect_uninstall_actions(
    hermes_home: Path | None = None,
    *,
    include_current: bool = False,
) -> list[UninstallAction]:
    resolved_hermes = (hermes_home or (Path.home() / ".hermes")).expanduser().resolve()
    plugins_root = resolved_hermes / "plugins"
    candidates: list[tuple[Path, str, bool]] = []
    for name in LEGACY_PLUGIN_ENTRIES:
        candidates.append((plugins_root / name, "legacy Hermes plugin entry", True))
    for name in LEGACY_RUNTIME_DIRS:
        candidates.append((resolved_hermes / name, "legacy coding runtime root", True))
    candidates.append((plugins_root / CURRENT_PLUGIN_ENTRY, "current Hermes plugin symlink", include_current))
    candidates.append((resolved_hermes / CURRENT_RUNTIME_DIR, "current coding runtime root", include_current))

    actions: list[UninstallAction] = []
    seen: set[Path] = set()
    for path, reason, removable in candidates:
        normalized = _normalize_hermes_child_path(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        _ensure_child_path(normalized, resolved_hermes)
        actions.append(
            UninstallAction(
                path=normalized,
                kind=_path_kind(normalized),
                reason=reason,
                existed=normalized.exists() or normalized.is_symlink(),
                removable=removable,
            )
        )
    return actions


def uninstall_hermes_coding_components(
    hermes_home: Path | None = None,
    *,
    include_current: bool = False,
    execute: bool = False,
) -> list[UninstallAction]:
    actions = collect_uninstall_actions(
        hermes_home=hermes_home,
        include_current=include_current,
    )
    if not execute:
        return actions

    removed_actions: list[UninstallAction] = []
    for action in actions:
        removed = False
        if action.existed and action.removable:
            _remove_path(action.path)
            removed = True
        removed_actions.append(
            UninstallAction(
                path=action.path,
                kind=action.kind,
                reason=action.reason,
                existed=action.existed,
                removable=action.removable,
                removed=removed,
            )
        )
    return removed_actions
