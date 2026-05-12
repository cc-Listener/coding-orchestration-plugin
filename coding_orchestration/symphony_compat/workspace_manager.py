from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class WorkspaceManager:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def create_workspace(self, project_path: Path, task_id: str, run_id: str, base_branch: str | None = None) -> Path:
        target = self.workspace_root / task_id / run_id
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"workspace already exists: {target}")

        if self._is_git_repo(project_path):
            try:
                self._create_git_worktree(project_path, target, base_branch=base_branch)
                return target
            except Exception:
                if target.exists():
                    shutil.rmtree(target)

        ignore = shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__")
        shutil.copytree(project_path, target, ignore=ignore)
        return target

    @staticmethod
    def _is_git_repo(path: Path) -> bool:
        return (path / ".git").exists()

    @staticmethod
    def _create_git_worktree(project_path: Path, target: Path, base_branch: str | None = None) -> None:
        command = ["git", "worktree", "add", str(target)]
        if base_branch:
            command.append(base_branch)
        subprocess.run(command, cwd=project_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def cleanup_workspace(self, workspace_path: Path) -> None:
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
