from __future__ import annotations

from typing import Any

from ...ports import KnowledgePort


class RunSummaryWriter:
    def __init__(self, knowledge: KnowledgePort):
        self.knowledge = knowledge

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
        return self.knowledge.write_run_summary(
            task_id=task_id,
            run_id=run_id,
            runner=runner,
            project=project,
            report=report,
            summary=summary,
        )
