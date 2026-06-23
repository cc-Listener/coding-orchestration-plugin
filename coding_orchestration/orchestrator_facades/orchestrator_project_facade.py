from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import gateway_active_context, gateway_project_context, project_profile_catalog
from ..models import MatchEvidence, ProjectResolveResult, TaskPhase, TaskStatus
from ..project_knowledge_initializer import ProjectKnowledgeInitializer
from ..project_resolver import Project
from ..project_resolver import normalize_text as normalize_project_text


class OrchestratorProjectFacadeMixin:
    def _format_project_list(self, *, active_project: dict[str, Any] | None) -> str:
        return self._project_profile_catalog().format_list(active_project=active_project)

    def _format_project_status(self, project: dict[str, Any]) -> str:
        return self._project_profile_catalog().format_status(project)

    def _known_project_profiles(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._project_profile_catalog().known_profiles(limit=limit)

    def _find_project_profile(self, project_name_or_alias: str) -> dict[str, Any] | None:
        return self._project_profile_catalog().find(project_name_or_alias)

    def _project_profile_from_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        return self._project_profile_catalog().profile_from_doc(doc)

    def _dynamic_source_count_for_project(self, project_name: str) -> int:
        return self._project_profile_catalog().dynamic_source_count(project_name)

    def _project_profile_catalog(self) -> project_profile_catalog.ProjectProfileCatalog:
        return project_profile_catalog.ProjectProfileCatalog(
            wiki=self.wiki,
            registry_projects=lambda: self.resolver.registry.projects,
        )

    def _bind_active_project_for_event(self, project: dict[str, Any], event: Any | None) -> bool:
        return self.gateway_binding_service.bind_active_project_for_event(project, event)

    def _active_project_for_event(self, event: Any | None) -> dict[str, Any] | None:
        return self.gateway_binding_service.active_project_for_event(
            event,
            find_project_profile=self._find_project_profile,
        )

    def _active_project_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.active_project_binding_key_for_event(event)

    def _apply_project_clarification(self, task: dict[str, Any], text: str) -> ProjectResolveResult | None:
        if task.get("project_path"):
            return None
        combined_text = "\n".join(
            part
            for part in [
                str(task.get("requirement_summary") or ""),
                normalize_project_text(text),
            ]
            if part
        )
        resolved = self.resolver.resolve(combined_text)
        if not resolved.project_path:
            resolved = self._resolve_local_project_from_human_text(combined_text)
        if not resolved or not resolved.project_path or not resolved.project_name:
            return None

        evidence = [
            {"source": item.source, "value": item.value, "score": item.score}
            for item in resolved.match_evidence
        ]
        self.ledger.update_project_context(
            task["task_id"],
            project_name=resolved.project_name,
            project_path=resolved.project_path,
            confidence=resolved.confidence,
            match_evidence=evidence,
        )
        self._transition_task_status(
            task["task_id"],
            TaskStatus.PLANNED,
            phase=TaskPhase.PLANNING,
            reason="project context resolved",
        )
        return resolved

    def _resolve_local_project_from_human_text(
        self,
        text: str,
        *,
        extra_candidates: tuple[str, ...] | list[str] = (),
    ) -> ProjectResolveResult | None:
        candidates = [*extra_candidates, *self._project_folder_candidates_from_text(text)]
        for candidate in self._unique_project_candidates(candidates):
            resolved = self._resolve_local_project_candidate(candidate, text)
            if resolved is not None:
                return resolved
        return None

    def _resolve_local_project_candidate(self, candidate: str, text: str) -> ProjectResolveResult | None:
        project_path = self._local_project_path_for_candidate(candidate)
        if project_path is None:
            return None
        project_name = project_path.name
        aliases = self._project_aliases_from_human_text(text, project_name)
        normalized_candidate = normalize_project_text(candidate).strip()
        if normalized_candidate and normalized_candidate not in aliases:
            aliases.append(normalized_candidate)
        self._upsert_human_project_profile(
            project_name=project_name,
            project_path=project_path,
            aliases=aliases,
            body=text,
        )
        return ProjectResolveResult(
            project_name=project_name,
            project_path=str(project_path),
            confidence=1.0,
            match_evidence=[MatchEvidence("human_project_folder", candidate, 1.0)],
            candidates=[],
            needs_human=False,
        )

    @staticmethod
    def _unique_project_candidates(candidates: list[str]) -> list[str]:
        return gateway_project_context.unique_project_candidates(candidates)

    def _apply_active_project_to_task_if_missing(self, task: dict[str, Any], event: Any | None) -> dict[str, Any]:
        return gateway_active_context.apply_active_project_to_task_if_missing(self, task, event)

    @staticmethod
    def _project_folder_candidates_from_text(text: str) -> list[str]:
        return gateway_project_context.project_folder_candidates_from_text(text)

    def _local_project_path_for_candidate(self, candidate: str) -> Path | None:
        return gateway_project_context.local_project_path_for_candidate(
            candidate,
            search_roots=self._local_project_search_roots(),
        )

    def _local_project_search_roots(self) -> list[Path]:
        return gateway_project_context.local_project_search_roots(
            registry_project_paths=[project.path for project in self.resolver.registry.projects],
            extra_roots=self.local_project_search_roots or [Path.home() / "Desktop" / "project"],
        )

    @staticmethod
    def _project_aliases_from_human_text(text: str, project_name: str) -> list[str]:
        return gateway_project_context.project_aliases_from_human_text(text, project_name)

    def _upsert_human_project_profile(
        self,
        *,
        project_name: str,
        project_path: Path,
        aliases: list[str],
        body: str,
    ) -> None:
        try:
            ProjectKnowledgeInitializer().bootstrap_project(
                self.wiki,
                Project(
                    name=project_name,
                    path=str(project_path),
                    aliases=tuple(aliases),
                    keywords=tuple(aliases),
                ),
            )
            return
        except Exception:
            self.wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": f"{project_name} 项目画像",
                    "body": body,
                    "project": project_name,
                    "project_id": project_name,
                    "name": project_name,
                    "aliases": aliases,
                    "local_paths": [str(project_path)],
                    "keywords": aliases,
                    "source_refs": [{"type": "human_clarification", "project_path": str(project_path)}],
                    "confidence": "high",
                    "status": "verified",
                },
                options={"dedupe_key": f"project:{project_name}"},
            )
