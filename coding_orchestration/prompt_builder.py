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
- Write `summary.md` for human review.
- Write `report.json` matching the runner schema.
- Do not publish, merge, or operate Feishu directly.
"""

    @staticmethod
    def _bullets(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- none"
