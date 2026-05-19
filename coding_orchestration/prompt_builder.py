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
- Do not operate Feishu directly.
{self._mode_output_policy(mode)}
"""

    @staticmethod
    def _bullets(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- none"

    @staticmethod
    def _confirmed_plan_block(mode: RunMode, confirmed_plan: str) -> str:
        if mode == RunMode.MERGE_TEST:
            context = confirmed_plan.strip() or "- No previous implementation context was found."
            return f"""## Previous Implementation Context
{context}"""
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
        if mode == RunMode.PLAN_ONLY:
            return """## Plan-only Contract
- 当前由 Hermes 进入 Codex plan-only 阶段；只允许输出计划，不允许修改文件、创建分支、运行发布或 merge。
- 计划必须像 Codex Plan 模式一样可供人工审核，明确目标、范围、涉及文件、实现步骤、测试命令、风险和待确认问题。
- 如果需求缺少关键信息，返回 `status=blocked` 或 `human_required=true`，并在 `next_actions` 里列出需要人确认的问题。
- 计划完成后停止；不要进入 implementation。"""
        if mode == RunMode.MERGE_TEST:
            workspace = workspace_path or "(not provided)"
            return f"""## Merge-to-test Contract
- This is a Hermes-controlled post-review merge-to-test handoff. The human has already reviewed/tested the implementation and explicitly requested merge-to-test.
- You are resuming the same Codex task session when possible. Continue from the implementation context, source branch, and worktree already established for this task.
- Use the `merge-to-test` skill exactly. It is allowed to commit tracked source-branch changes, push the source branch to origin, merge the source branch into `test`, and push `origin/test`.
- Do not publish or deploy any environment. Publishing remains manual.
- Current task worktree/workspace: `{workspace}`.
- Original project directory: `{project_path}`.
- If git refuses to switch to `test` because another worktree already has it checked out, use the repository context to choose the least risky merge-to-test workflow. Stop with `status=blocked` if doing so would require guessing or overwriting unrelated work.

## Merge Watchdog Checklist
- Confirm the source branch before committing or pushing.
- Inspect `git status --short` and do not include unrelated untracked files without explicit user confirmation.
- Push the source branch to `origin` before or during the merge workflow.
- Merge into `test` and push `origin/test`.
- Return `status=success` only if the source branch push, merge into `test`, and `origin/test` push completed or were already up to date with concrete git evidence.
- Return `status=blocked` if there are conflicts or unrelated local changes that cannot be safely resolved."""
        if mode != RunMode.IMPLEMENTATION:
            return ""
        workspace = workspace_path or "(not provided)"
        return f"""## GitOps Implementation Contract
- This is the post-plan implementation handoff. Follow the confirmed plan above unless it is unsafe or incomplete.
- Use the Codex superpowers workflow before editing: `using-superpowers`, `using-git-worktrees`, `test-driven-development`, and `verification-before-completion` when available.
- Hermes has already launched you inside a task-scoped Hermes-controlled worktree/workspace: `{workspace}`.
- Treat the current working directory as the implementation worktree. Do not modify the original project directory directly: `{project_path}`.
- If the current working directory is not an isolated worktree/workspace, stop and return `status=blocked` with the isolation issue.
- Do not create a nested worktree unless the superpowers workflow explicitly requires it after detecting that Hermes did not provide a valid isolated workspace.

## GitOps Watchdog Checklist
- Confirm the current branch/worktree before editing and mention it in `summary_markdown`.
- Keep all edits inside the allowed paths and avoid forbidden paths.
- Run the project test commands when feasible; otherwise report why each command was not run.
- Produce a complete structured report for Hermes. If any contract item cannot be satisfied, return `status=blocked` rather than continuing loosely."""

    @staticmethod
    def _mode_output_policy(mode: RunMode) -> str:
        if mode == RunMode.MERGE_TEST:
            return "- Merge/push to `test` is allowed only for this merge-test run. Do not publish or deploy."
        return "- Do not publish, merge, or operate Feishu directly."
