from __future__ import annotations

from pathlib import Path


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
