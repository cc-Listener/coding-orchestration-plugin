from __future__ import annotations

from pathlib import Path
from typing import Any


def compute_plugin_link(repo_root: Path, hermes_home: Path) -> tuple[Path, Path]:
    source = repo_root / "coding_orchestration"
    target = hermes_home / "plugins" / "coding_orchestration"
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


def read_hermes_feishu_app_id(hermes_home: Path | None = None) -> str:
    resolved_hermes = (hermes_home or (Path.home() / ".hermes")).expanduser().resolve()
    env_path = resolved_hermes / ".env"
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


def run_install_preflight(hermes_home: Path | None = None) -> dict[str, Any]:
    resolved_hermes = (hermes_home or (Path.home() / ".hermes")).expanduser().resolve()
    expected_app_id = read_hermes_feishu_app_id(resolved_hermes)
    if not expected_app_id:
        return {
            "ok": False,
            "status": "missing_hermes_app",
            "error": f"FEISHU_APP_ID is missing in {resolved_hermes / '.env'}",
            "recovery_action": "Configure Hermes Feishu app first, then bind terminal lark-cli to the same app before installing.",
            "expected_app_id": "",
            "actual_app_id": "",
        }
    from .source_resolver import SourceResolver

    return SourceResolver().preflight_lark(
        {
            "expected_app_id": expected_app_id,
            "hermes_home": str(resolved_hermes),
        }
    )
