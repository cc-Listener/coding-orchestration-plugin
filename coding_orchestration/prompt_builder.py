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
        workflow: WorkflowSpec,
        wiki_refs: list[dict[str, Any]],
        mode: RunMode,
        runner_name: str,
    ) -> str:
        wiki_block = "\n".join(
            f"- {ref.get('id')}: {ref.get('title')}\n  {ref.get('body', '')}"
            for ref in wiki_refs
        ) or "- none"
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
