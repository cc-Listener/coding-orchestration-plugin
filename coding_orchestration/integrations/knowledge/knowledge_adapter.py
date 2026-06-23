from __future__ import annotations

"""KnowledgePort adapter backed by the local LLM Wiki integration."""

from pathlib import Path
from typing import Any

from .llm_wiki_adapter import LocalLlmWikiAdapter


class LocalKnowledgeAdapter:
    """KnowledgePort implementation backed by the local LLM Wiki layout."""

    def __init__(self, wiki: LocalLlmWikiAdapter):
        self.wiki = wiki

    @classmethod
    def from_root(cls, root: Path) -> "LocalKnowledgeAdapter":
        return cls(LocalLlmWikiAdapter(root))

    @property
    def root(self) -> Path:
        return self.wiki.root

    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.wiki.search(query, filters)

    def read(self, ref_id: str) -> dict[str, Any] | None:
        return self.wiki.read(ref_id)

    def find_by_source_task(self, task_id: str) -> list[dict[str, Any]]:
        return self.wiki.find_by_source_task(task_id)

    def delete_by_source_task(self, task_id: str) -> int:
        return self.wiki.delete_by_source_task(task_id)

    def find_by_kind(self, kind: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.wiki.find_by_kind(kind, filters)

    def upsert(self, document: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.wiki.upsert(document, options)

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
        return self.upsert(
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
