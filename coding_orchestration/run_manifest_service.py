from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import RunManifest, RunMode, RunnerName, TaskPhase
from .source_projection import source_projection_from_source


CODEX_SESSION_RUNNERS = {
    RunnerName.CODEX_CLI.value,
    RunnerName.HERMES_AUTONOMOUS_CODEX.value,
}


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def is_codex_session_runner(runner_name: str) -> bool:
    return runner_name in CODEX_SESSION_RUNNERS


def runner_name_for_manifest(runner_name: str) -> RunnerName | str:
    if runner_name == RunnerName.CODEX_CLI.value:
        return RunnerName.CODEX_CLI
    if runner_name == RunnerName.HERMES_AUTONOMOUS_CODEX.value:
        return RunnerName.HERMES_AUTONOMOUS_CODEX
    return runner_name


def codex_attach_command(session_id: str) -> str:
    return f"codex resume {session_id}" if session_id else ""


def codex_resume_command(
    session_id: str,
    mode: RunMode | str | None = None,
    *,
    dangerous_bypass: bool = False,
) -> str:
    if not session_id:
        return ""
    mode_value = mode.value if isinstance(mode, RunMode) else str(mode or "")
    if dangerous_bypass or mode_value in {
        RunMode.IMPLEMENTATION.value,
        RunMode.QA.value,
        RunMode.MERGE_TEST.value,
    }:
        return f"codex exec resume --dangerously-bypass-approvals-and-sandbox {session_id} -"
    return f'codex exec resume -c sandbox_mode="read-only" -c approval_policy="never" {session_id} -'


def build_manifest_session_fields(
    *,
    session_id: str,
    runner_name: str,
    mode: RunMode | str | None,
    dangerous_bypass: bool = False,
    existing_resume_session_id: str | None = None,
    existing_session_visibility: str | None = None,
    force_visible: bool = False,
) -> dict[str, str]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return {}
    fields = {
        "session_id": normalized_session_id,
        "resume_session_id": str(existing_resume_session_id or "").strip() or normalized_session_id,
    }
    if is_codex_session_runner(runner_name):
        visibility = "visible" if force_visible else (str(existing_session_visibility or "").strip() or "visible")
        fields.update(
            {
                "attach_command": codex_attach_command(normalized_session_id),
                "resume_command": codex_resume_command(
                    normalized_session_id,
                    mode=mode,
                    dangerous_bypass=dangerous_bypass,
                ),
                "session_visibility": visibility,
            }
        )
    return fields


def mode_uses_controlled_bypass(mode: RunMode) -> bool:
    return mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}


def run_uses_controlled_bypass(mode: RunMode, source: dict[str, Any] | None = None) -> bool:
    if mode_uses_controlled_bypass(mode):
        return True
    return mode == RunMode.PLAN_ONLY and source_requires_codex_plan_permissions(source)


def source_requires_codex_plan_permissions(source: dict[str, Any] | None) -> bool:
    if not isinstance(source, dict):
        return False
    source_projection = source_projection_from_source(source)
    if (
        source_projection.status == "missing"
        and not source_projection.source_type
        and not source_projection.url
        and not source_projection.legacy_context
    ):
        return False
    if source_projection.status == "ok":
        return False
    source_type = source_projection.source_type.strip().lower()
    url = source_projection.url.strip().lower()
    if (
        source_projection.codex_resolvable
        or source_projection.resolution_owner == "codex"
        or source_projection.lark_cli_command
    ):
        return True
    return (
        source_type.startswith("feishu_doc")
        or source_type.startswith("feishu_wiki")
        or source_type.startswith("feishu_project_")
        or "feishu.cn" in url
    )


def permission_profile(mode: RunMode, *, source_elevated: bool = False) -> str:
    if mode == RunMode.DECOMPOSITION:
        return "decomposition_read_only"
    if mode == RunMode.PLAN_ONLY:
        if source_elevated:
            return "plan_source_read_elevated"
        return "plan_read_only"
    if mode == RunMode.IMPLEMENTATION:
        return "implementation_controlled_elevated"
    if mode == RunMode.QA:
        return "qa_controlled_elevated"
    if mode == RunMode.MERGE_TEST:
        return "merge_test_git_elevated"
    return "default"


def elevated_permissions_reason(mode: RunMode, *, source_elevated: bool = False) -> str:
    if mode == RunMode.PLAN_ONLY:
        if source_elevated:
            return (
                "Plan-only has an unresolved external source. Codex needs the same terminal-level "
                "access as an interactive Codex session to run rtk lark-cli, read Feishu/Lark documents, "
                "and inspect authenticated planning context before producing a safe plan."
            )
        return (
            "Plan-only may need to read Feishu/Lark documents, Swagger/OpenAPI specs, "
            "private API metadata, package metadata, and authenticated context sources before producing a plan."
        )
    if mode == RunMode.QA:
        return (
            "QA requires dependency install, test execution, dev server/browser automation, "
            "git metadata writes for QA fix commits, and QA artifact writes."
        )
    if mode == RunMode.IMPLEMENTATION:
        return (
            "Implementation requires dependency install, test execution, dev server/browser checks, "
            "and git metadata writes before QA."
        )
    return "Merge-test requires git merge and push operations against the test branch."


def elevated_permission_scope(mode: RunMode, *, source_elevated: bool = False) -> list[str]:
    if mode == RunMode.PLAN_ONLY:
        if source_elevated:
            return [
                "project file reads",
                "rtk lark-cli document reads",
                "Feishu/Lark auth cache reads or refreshes available to the Codex CLI session",
                "Swagger/OpenAPI reads",
                "private API metadata reads",
                "network reads for planning context",
                "no project file writes",
            ]
        return [
            "project file reads",
            "Feishu/Lark document reads",
            "Swagger/OpenAPI reads",
            "private API metadata reads",
            "network reads for planning context",
            "no project file writes",
        ]
    if mode == RunMode.MERGE_TEST:
        return ["git metadata", "source branch push", "test branch merge and push"]
    return [
        "dependency install",
        "package manager caches",
        "git metadata",
        "dev server and browser QA",
        "QA reports",
    ]


def source_modification_boundary(
    mode: RunMode,
    workspace_path: Path | None,
    project_path: Path | None = None,
) -> str:
    if mode == RunMode.PLAN_ONLY:
        project = str(project_path) if project_path else "project workspace"
        return (
            f"plan-only may read project files under {project} and external planning context "
            "such as Feishu/Lark docs, Swagger/OpenAPI, and API metadata; it must not modify project files."
        )
    workspace = str(workspace_path) if workspace_path else "task workspace"
    return (
        f"source code changes must stay within {workspace}; writes outside the workspace are limited to "
        "dependency caches, git metadata, dev server/browser temporary files, and QA artifacts required for verification."
    )


def build_start_manifest_updates(
    *,
    mode: RunMode,
    source: dict[str, Any] | None,
    runner_name: str,
    resume_session_id: str,
    existing_resume_session_id: str | None,
    existing_session_visibility: str | None,
    workspace_path: Path | None,
    project_path: Path | None,
    checkpoint_target_branch: str = "",
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    uses_controlled_bypass = run_uses_controlled_bypass(mode, source)
    if resume_session_id:
        updates.update(
            build_manifest_session_fields(
                session_id=resume_session_id,
                runner_name=runner_name,
                mode=mode,
                dangerous_bypass=uses_controlled_bypass,
                existing_resume_session_id=existing_resume_session_id,
                existing_session_visibility=existing_session_visibility,
                force_visible=True,
            )
        )
    if uses_controlled_bypass:
        source_elevated = mode == RunMode.PLAN_ONLY
        updates.update(
            {
                "dangerous_bypass": True,
                "permission_profile": permission_profile(mode, source_elevated=source_elevated),
                "elevated_permissions_reason": elevated_permissions_reason(mode, source_elevated=source_elevated),
                "elevated_permission_scope": elevated_permission_scope(mode, source_elevated=source_elevated),
                "source_modification_boundary": source_modification_boundary(
                    mode,
                    workspace_path,
                    project_path,
                ),
            }
        )
    if checkpoint_target_branch:
        updates["target_branch"] = checkpoint_target_branch
    return updates


def artifact_record(artifacts: Any) -> dict[str, str]:
    operator_log = getattr(artifacts, "operator_log", None) or artifacts.run_dir / "run-log.md"
    execution_policy = getattr(artifacts, "execution_policy", None) or artifacts.run_dir / "execution-policy.json"
    context_manifest = getattr(artifacts, "context_manifest", None) or artifacts.run_dir / "context-manifest.json"
    return {
        "run_dir": str(artifacts.run_dir),
        "input_prompt": str(artifacts.input_prompt),
        "manifest": str(artifacts.manifest),
        "stdout": str(artifacts.stdout),
        "stderr": str(artifacts.stderr),
        "events": str(artifacts.events),
        "report": str(artifacts.report),
        "summary": str(artifacts.summary),
        "diff": str(artifacts.diff),
        "operator_log": str(operator_log),
        "execution_policy": str(execution_policy),
        "context_manifest": str(context_manifest),
    }


def build_run_manifest(
    *,
    task: dict[str, Any],
    run_id: str,
    mode: RunMode,
    runner_name: str,
    project_path: Path,
    workspace_path: Path | None,
    workflow: Any,
    wiki_refs: list[dict[str, Any]],
    timeout_seconds: int,
    run_dir: Path,
    heartbeat_interval_seconds: int,
    execution_policy: dict[str, Any],
    source_branch: str | None = None,
    source_base_branch: str | None = None,
    now: datetime | None = None,
) -> RunManifest:
    created_at = now or datetime.now(timezone.utc)
    return RunManifest(
        task_id=task["task_id"],
        run_id=run_id,
        mode=mode,
        runner=runner_name_for_manifest(runner_name),
        source=task["source"],
        project_path=str(project_path),
        workspace_path=str(workspace_path) if workspace_path else None,
        workflow_refs=[str(project_path / "WORKFLOW.md")],
        llm_wiki_refs=[str(ref.get("id")) for ref in wiki_refs],
        allowed_paths=list(workflow.allowed_paths),
        forbidden_paths=list(workflow.forbidden_paths),
        task_phase=str(task.get("phase") or TaskPhase.DRAFT.value),
        source_branch=source_branch,
        source_base_branch=source_base_branch,
        timeout_seconds=timeout_seconds,
        deadline_at=(created_at + timedelta(seconds=timeout_seconds)).isoformat(),
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        output_schema_path=str(run_dir / "report.schema.json"),
        created_at=created_at.isoformat(),
        session_visibility="visible" if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} else "background",
        permission_profile=permission_profile(mode),
        execution_policy=execution_policy,
    )


def update_manifest_session_metadata(
    *,
    manifest_path: Path,
    session_id: str,
    runner_name: str,
) -> None:
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(manifest, dict):
        return
    manifest.update(
        build_manifest_session_fields(
            session_id=session_id,
            runner_name=runner_name,
            mode=manifest.get("mode"),
            dangerous_bypass=bool(manifest.get("dangerous_bypass")),
            existing_resume_session_id=manifest.get("resume_session_id"),
            existing_session_visibility=manifest.get("session_visibility"),
        )
    )
    manifest_path.write_text(json_dumps(manifest), encoding="utf-8")


class RunManifestService:
    def build_manifest(self, **kwargs: Any) -> RunManifest:
        return build_run_manifest(**kwargs)

    def update_session_metadata(self, **kwargs: Any) -> None:
        update_manifest_session_metadata(**kwargs)
