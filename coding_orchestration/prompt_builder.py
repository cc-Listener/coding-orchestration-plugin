from __future__ import annotations

from typing import Any

from .models import RunMode
from .symphony_compat.workflow_loader import WorkflowSpec


class PromptBuilder:
    def build(
        self,
        *,
        requirement_summary: str,
        source: dict[str, Any],
        project_path: str,
        workspace_path: str | None = None,
        workflow: WorkflowSpec,
        wiki_refs: list[dict[str, Any]],
        mode: RunMode,
        runner_name: str,
        confirmed_plan: str = "",
    ) -> str:
        wiki_block = "\n".join(
            f"- {ref.get('id')}: {ref.get('title')}\n  {ref.get('body', '')}"
            for ref in wiki_refs
        ) or "- none"
        confirmed_plan_block = self._confirmed_plan_block(mode, confirmed_plan)
        execution_contract = self._execution_contract(
            mode=mode,
            project_path=project_path,
            workspace_path=workspace_path,
        )
        return f"""# Coding Task

## Requirement
{requirement_summary}

## Source
{source}

## Project
{project_path}

## Mode
{mode.value}

## Runner
{runner_name}

## Workflow
Allowed Paths:
{self._bullets(workflow.allowed_paths)}

Forbidden Paths:
{self._bullets(workflow.forbidden_paths)}

Test Commands:
{self._bullets(workflow.default_test_commands)}

Merge Policy: {workflow.merge_policy}
Publish Policy: {workflow.publish_policy}

## LLM Wiki References
{wiki_block}

{confirmed_plan_block}

{execution_contract}

## Required Outputs
- Return a final JSON object matching the runner schema.
- Put the human-readable plan or implementation summary in `summary_markdown`; Hermes will persist it to `summary.md` and show it in Feishu for human confirmation.
- In plan-only mode, `summary_markdown` must contain a concrete plan with scope, files/modules to inspect, implementation steps, tests to run, risks, and open questions.
- In plan-only mode, do not modify files; set `human_required` to true when the plan needs confirmation before implementation.
- Use `test_results` entries shaped as `{{"command":"...","status":"passed|failed|not_run|blocked","output_summary":"..."}}`.
- Do not publish, merge, or operate Feishu directly.
"""

    @staticmethod
    def _bullets(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- none"

    @staticmethod
    def _confirmed_plan_block(mode: RunMode, confirmed_plan: str) -> str:
        if mode != RunMode.IMPLEMENTATION:
            return ""
        plan = confirmed_plan.strip() or (
            "- No prior plan-only summary was found. If the implementation cannot proceed safely, "
            "return `status=blocked` and explain what human confirmation is missing."
        )
        return f"""## Confirmed Plan From Plan-only Run
{plan}"""

    @staticmethod
    def _execution_contract(mode: RunMode, project_path: str, workspace_path: str | None) -> str:
        if mode != RunMode.IMPLEMENTATION:
            return ""
        workspace = workspace_path or "(not provided)"
        return f"""## Codex Superpowers Execution Contract
- This is the post-plan implementation handoff. Follow the confirmed plan above unless it is unsafe or incomplete.
- Use the Codex superpowers workflow before editing: `using-superpowers`, `using-git-worktrees`, `test-driven-development`, and `verification-before-completion` when available.
- Hermes has already launched you inside a task-scoped Hermes-controlled worktree/workspace: `{workspace}`.
- Treat the current working directory as the implementation worktree. Do not modify the original project directory directly: `{project_path}`.
- If the current working directory is not an isolated worktree/workspace, stop and return `status=blocked` with the isolation issue.
- Do not create a nested worktree unless the superpowers workflow explicitly requires it after detecting that Hermes did not provide a valid isolated workspace."""
