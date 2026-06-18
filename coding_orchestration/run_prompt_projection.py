from __future__ import annotations

from typing import Any

from .models import RunMode


def build_run_prompt_text(
    *,
    prompt_builder: Any,
    task_id: str,
    mode: RunMode,
    runner_name: str,
    project_path: Any,
    workspace_path: Any | None,
    resume_session_id: str,
    incremental_context: str,
    requirement_summary: str,
    source: dict[str, Any],
    workflow: Any,
    wiki_docs: list[dict[str, Any]],
    confirmed_context: str,
    context_artifacts: dict[str, str],
    execution_policy: dict[str, Any],
) -> str:
    project_path_value = str(project_path)
    workspace_path_value = str(workspace_path) if workspace_path else None
    if resume_session_id:
        return prompt_builder.build_incremental(
            task_id=task_id,
            mode=mode,
            runner_name=runner_name,
            project_path=project_path_value,
            workspace_path=workspace_path_value,
            resume_session_id=resume_session_id,
            incremental_context=incremental_context,
            context_artifacts=context_artifacts,
            execution_policy=execution_policy,
        )
    return prompt_builder.build(
        requirement_summary=requirement_summary,
        source=source,
        project_path=project_path_value,
        workspace_path=workspace_path_value,
        workflow=workflow,
        wiki_refs=wiki_docs,
        mode=mode,
        runner_name=runner_name,
        confirmed_plan=confirmed_context,
        context_artifacts=context_artifacts,
        execution_policy=execution_policy,
    )
