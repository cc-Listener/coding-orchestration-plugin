from __future__ import annotations

from typing import Any

from .llm_wiki_adapter import LocalLlmWikiAdapter


class RunSummaryWriter:
    def __init__(self, wiki: LocalLlmWikiAdapter):
        self.wiki = wiki

    def write_run_summary(
        self,
        *,
        task_id: str,
        run_id: str,
        runner: str,
        project: str,
        report: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        body = "\n".join(
            [
                summary,
                "",
                f"Status: {report.get('status')}",
                f"Runner: {runner}",
                f"Tests: {', '.join(report.get('test_commands') or []) or 'none'}",
                f"Risks: {', '.join(report.get('risks') or []) or 'none'}",
                f"Next: {', '.join(report.get('next_actions') or []) or 'none'}",
            ]
        )
        return self.wiki.upsert(
            {
                "kind": "run_summary",
                "title": f"{project} run summary {run_id}",
                "body": body,
                "source_refs": [{"type": "task", "task_id": task_id, "run_id": run_id}],
                "project": project,
                "module": None,
                "tags": ["coding_run", runner],
                "confidence": "medium",
                "status": "draft",
                "runner": runner,
            },
            options={"dedupe_key": f"{task_id}:{run_id}:run_summary"},
        )
