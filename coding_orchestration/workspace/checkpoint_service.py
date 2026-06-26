from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ..models import RunMode


SOURCE_BRANCH_PREFIX = "feature"
SOURCE_BRANCH_SLUG_MAX_LENGTH = 64


class WorkspaceCheckpointService:
    def __init__(self, workspace_manager: Any):
        self.workspace_manager = workspace_manager

    def implementation_workspace(self, task: dict[str, Any], project_path: Path, run_id: str) -> Path:
        reusable = latest_existing_implementation_workspace(task)
        if reusable is not None:
            return reusable
        project_name = task.get("source", {}).get("project_name") or project_path.name
        return self.workspace_manager.create_workspace(
            project_path=project_path,
            task_id=task["task_id"],
            run_id=run_id,
            base_branch=source_base_branch_for_task(task),
            branch_name=source_branch_for_task(task, str(project_name)),
        )

    def merge_test_workspace(self, task: dict[str, Any]) -> Path | None:
        reusable = latest_existing_implementation_workspace(task)
        if reusable is not None:
            return reusable
        session = task.get("task_session") or {}
        worktree = session.get("worktree_path")
        if worktree:
            path = Path(str(worktree)).expanduser()
            if path.exists():
                return path.resolve()
        return None


def diff_guard_changed_files_for_mode(mode: RunMode, changed_files: list[str]) -> list[str]:
    if mode != RunMode.QA:
        return changed_files
    return [
        path
        for path in changed_files
        if not path.startswith(".gstack/qa-reports/")
    ]


def collect_qa_artifacts(workspace_path: Path | None) -> dict[str, str]:
    if workspace_path is None:
        return {}
    qa_dir = workspace_path / ".gstack" / "qa-reports"
    if not qa_dir.exists():
        return {}
    reports = sorted(qa_dir.glob("qa-report-*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    baseline = qa_dir / "baseline.json"
    screenshots = qa_dir / "screenshots"
    artifacts: dict[str, str] = {}
    if reports:
        artifacts["report"] = str(reports[0])
    if baseline.exists():
        artifacts["baseline"] = str(baseline)
    if screenshots.exists():
        artifacts["screenshots_dir"] = str(screenshots)
    return artifacts


def prepare_qa_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
    return workspace_clean_checkpoint(workspace_path)


def prepare_merge_test_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
    return workspace_clean_checkpoint(workspace_path)


def workspace_has_uncommitted_changes(workspace_path: Path | None) -> bool:
    checkpoint = workspace_clean_checkpoint(workspace_path)
    return checkpoint.get("status") == "failed"


def workspace_clean_checkpoint(workspace_path: Path | None) -> dict[str, str]:
    if workspace_path is None:
        return {"status": "skipped", "reason": "no_workspace"}
    if not (workspace_path / ".git").exists():
        return {"status": "skipped", "reason": "not_git_repo"}
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if status.stdout.strip():
            return {
                "status": "failed",
                "reason": "implementation_commit_missing",
                "error": "source worktree has uncommitted changes",
                "status_porcelain": status.stdout.strip(),
            }
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return {"status": "clean", "head": head.stdout.strip()}
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "implementation_commit_missing",
            "error": str(exc),
        }


def git_head(workspace_path: Path | None) -> str:
    if workspace_path is None or not (workspace_path / ".git").exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def source_branch_for_task(task: dict[str, Any], project_name: str) -> str:
    session = task.get("task_session") or {}
    existing = session.get("source_branch")
    if existing:
        return str(existing)
    plan_report = session.get("plan_report") or {}
    plan_candidate = plan_report.get("branch_slug_candidate") if isinstance(plan_report, dict) else ""
    candidates = [
        plan_candidate,
        task.get("requirement_summary"),
        project_name,
        "task",
    ]
    slug = ""
    for candidate in candidates:
        slug = slugify_ascii(str(candidate or ""))
        if slug:
            break
    if slug:
        slug = slug[:SOURCE_BRANCH_SLUG_MAX_LENGTH].rstrip("-")
    if not slug:
        slug = "task"
    return f"{SOURCE_BRANCH_PREFIX}/{slug}-{task_short_id(str(task['task_id']))}"


def source_base_branch_for_task(task: dict[str, Any]) -> str:
    session = task.get("task_session") or {}
    existing = session.get("source_base_branch")
    if existing:
        return str(existing)
    source = task.get("source") or {}
    configured = source.get("source_base_branch") or source.get("base_branch")
    return str(configured or "main")


def task_short_id(task_id: str) -> str:
    return task_id.removeprefix("task_")


def slugify_ascii(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def latest_existing_implementation_workspace(task: dict[str, Any]) -> Path | None:
    for run in reversed(task.get("agent_runs") or []):
        if run.get("mode") != RunMode.IMPLEMENTATION.value:
            continue
        workspace_path = run.get("workspace_path")
        if not workspace_path:
            continue
        path = Path(str(workspace_path))
        if path.exists():
            return path
    return None
