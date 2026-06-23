from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import RunMode
from ..source.source_projection import source_projection_from_source


@dataclass(frozen=True)
class ContextPackage:
    prompt_context: str
    manifest: dict[str, Any]
    manifest_path: Path


class ContextAssembler:
    _BUDGETS = {
        RunMode.DECOMPOSITION.value: 10000,
        RunMode.PLAN_ONLY.value: 12000,
        RunMode.IMPLEMENTATION.value: 12000,
        RunMode.QA.value: 9000,
        RunMode.MERGE_TEST.value: 6000,
    }

    def assemble(
        self,
        *,
        run_mode: RunMode | str,
        task: dict[str, Any],
        run_dir: Path,
        dependency_tasks: list[dict[str, Any]] | None = None,
        sibling_tasks: list[dict[str, Any]] | None = None,
    ) -> ContextPackage:
        mode = RunMode(run_mode)
        included: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        sections: list[str] = []

        self._include(
            sections,
            included,
            kind="current_task",
            source=str(task.get("task_id") or "task"),
            reason="Every run requires the current task goal and acceptance context.",
            text=self._current_task_block(task),
        )
        if mode == RunMode.DECOMPOSITION:
            self._include(
                sections,
                included,
                kind="project_index_summary",
                source="task_session.project_index_summary",
                reason="Decomposition needs project candidates without loading source code.",
                text=str((task.get("task_session") or {}).get("project_index_summary") or ""),
            )
            excluded.append(
                {
                    "kind": "source_code_fulltext",
                    "source": "repository",
                    "reason": "Decomposition decides delivery structure and should not receive repository source text.",
                }
            )
        elif mode == RunMode.IMPLEMENTATION:
            for dependency in dependency_tasks or []:
                self._include(
                    sections,
                    included,
                    kind="direct_dependency_summary",
                    source=str(dependency.get("task_id") or "dependency_task"),
                    reason="Implementation may depend on the latest accepted result of direct prerequisites.",
                    text=self._dependency_block(dependency),
                )
            for sibling in sibling_tasks or []:
                excluded.append(
                    {
                        "kind": "sibling_task",
                        "source": str(sibling.get("task_id") or "sibling_task"),
                        "task_id": sibling.get("task_id"),
                        "reason": "Sibling tasks are not direct prerequisites for this execution run.",
                    }
                )
        else:
            for dependency in dependency_tasks or []:
                self._include(
                    sections,
                    included,
                    kind="direct_dependency_summary",
                    source=str(dependency.get("task_id") or "dependency_task"),
                    reason="This run may need accepted prerequisite results.",
                    text=self._dependency_block(dependency),
                )

        manifest = {
            "run_mode": mode.value,
            "task_id": task.get("task_id"),
            "included": included,
            "excluded": excluded,
            "budget": {
                "max_tokens": self._BUDGETS.get(mode.value, 8000),
                "estimated_tokens": sum(item["token_estimate"] for item in included),
            },
        }
        manifest_path = run_dir / "context-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return ContextPackage(
            prompt_context="\n\n".join(section for section in sections if section.strip()),
            manifest=manifest,
            manifest_path=manifest_path,
        )

    @staticmethod
    def _include(
        sections: list[str],
        included: list[dict[str, Any]],
        *,
        kind: str,
        source: str,
        reason: str,
        text: str,
    ) -> None:
        clean = str(text or "").strip()
        if not clean:
            return
        sections.append(f"## {kind}\n{clean}")
        included.append(
            {
                "kind": kind,
                "source": source,
                "reason": reason,
                "token_estimate": max(1, len(clean) // 4),
            }
        )

    @staticmethod
    def _current_task_block(task: dict[str, Any]) -> str:
        session = task.get("task_session") or {}
        delivery = session.get("delivery") or {}
        criteria = "\n".join(f"- {item}" for item in delivery.get("acceptance_criteria") or [])
        source_projection = source_projection_from_source(task.get("source") or {})
        return "\n".join(
            [
                f"task_id: {task.get('task_id')}",
                f"task_kind: {task.get('task_kind') or 'execution'}",
                f"requirement_summary: {task.get('requirement_summary') or ''}",
                f"project_path: {task.get('project_path') or ''}",
                "acceptance_criteria:",
                criteria or "- none",
                f"source_summary: {source_projection.raw_fields_summary}",
            ]
        )

    @staticmethod
    def _dependency_block(task: dict[str, Any]) -> str:
        delivery = (task.get("task_session") or {}).get("delivery") or {}
        return "\n".join(
            [
                f"task_id: {task.get('task_id')}",
                f"status: {task.get('status') or ''}",
                f"summary: {task.get('requirement_summary') or ''}",
                f"completion_summary: {delivery.get('completion_summary') or ''}",
            ]
        )
