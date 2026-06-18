from __future__ import annotations

from typing import Any

from .models import RunMode
from .status_policy import run_details_are_runner_failed


def build_plan_report_session_fields(report: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "branch_slug_candidate",
        "execution_policy_decision",
        "user_facing_summary",
        "technical_summary",
        "next_actions",
    )
    return {field: report[field] for field in fields if field in report}


def build_plan_report_session_update(
    *,
    mode: RunMode,
    report: dict[str, Any],
    stale_completion: bool,
) -> dict[str, Any]:
    if stale_completion or mode != RunMode.PLAN_ONLY:
        return {}
    plan_report = build_plan_report_session_fields(report)
    if not plan_report:
        return {}
    return {"plan_report": plan_report}


def build_run_start_base_session_update(
    *,
    project_name: str,
    runner_name: str,
    mode: RunMode,
) -> dict[str, Any]:
    return {
        "project_name": project_name,
        "runner": {
            "provider": runner_name,
            "last_requested_mode": mode.value,
        },
    }


def build_run_start_workspace_session_update(
    *,
    mode: RunMode,
    source_branch: str,
    source_base_branch: str,
    workspace_path: Any,
    resume_session_id: str = "",
) -> dict[str, Any]:
    if mode not in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}:
        return {}
    update: dict[str, Any] = {
        "source_branch": source_branch,
        "source_base_branch": source_base_branch,
        "worktree_path": str(workspace_path),
    }
    if mode in {RunMode.QA, RunMode.MERGE_TEST}:
        update["runner"] = {
            "resume_session_id": resume_session_id,
        }
    return update


def build_active_run_session_update(
    *,
    run_id: str,
    mode: RunMode,
) -> dict[str, Any]:
    return {
        "runner": {
            "active_run_id": run_id,
            "active_mode": mode.value,
        }
    }


def build_runner_session_update(
    *,
    runner_name: str,
    run_id: str,
    status: str,
    report: dict[str, Any],
    session_id: str | None,
    run_still_active: bool,
    attach_command: str = "",
    reconciled_at: str = "",
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "provider": runner_name,
        "last_run_id": run_id,
        "last_run_status": status,
        "last_run_raw_status": str(report.get("raw_status") or ""),
    }
    if run_still_active:
        return update

    usable_session_id = "" if run_details_are_runner_failed(report) else str(session_id or "")
    update.update(
        {
            "active_run_id": None,
            "active_mode": None,
            "resume_session_id": usable_session_id,
            "thread_id": usable_session_id,
            "session_id": usable_session_id,
            "attach_command": attach_command if usable_session_id else "",
        }
    )
    if reconciled_at:
        update["reconciled_run_id"] = run_id
        update["reconciled_at"] = reconciled_at
    return update


def build_completion_session_update(
    *,
    mode: RunMode,
    report: dict[str, Any],
    stale_completion: bool,
    runner_name: str,
    run_id: str,
    status: str,
    session_id: str | None,
    run_still_active: bool,
    attach_command: str = "",
) -> dict[str, Any]:
    if stale_completion:
        return {}
    update = build_plan_report_session_update(
        mode=mode,
        report=report,
        stale_completion=stale_completion,
    )
    update["runner"] = build_runner_session_update(
        runner_name=runner_name,
        run_id=run_id,
        status=status,
        report=report,
        session_id=session_id,
        run_still_active=run_still_active,
        attach_command=attach_command,
    )
    return update
