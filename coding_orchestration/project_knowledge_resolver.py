from __future__ import annotations

from pathlib import Path
from typing import Any

from .llm_wiki_adapter import LocalLlmWikiAdapter
from .models import MatchEvidence, ProjectResolveResult
from .project_knowledge_initializer import ProjectKnowledgeInitializer
from .project_resolver import Project, ProjectRegistry, ProjectResolver


class ProjectKnowledgeResolver:
    """Resolve project identity from LLM Wiki project profiles first.

    ``project-registry.json`` is treated as bootstrap/fallback data. Durable,
    reusable project knowledge should live in LLM Wiki as ``project_profile``
    documents.
    """

    def __init__(self, *, wiki: LocalLlmWikiAdapter, fallback: ProjectResolver):
        self.wiki = wiki
        self.fallback = fallback

    @property
    def registry(self) -> ProjectRegistry:
        projects: list[dict[str, Any]] = []
        seen: set[str] = set()
        for doc in self._project_profile_docs():
            project = self._project_dict(doc)
            name = str(project.get("name") or "")
            if not name or name in seen:
                continue
            projects.append(project)
            seen.add(name)
        for project in self.fallback.registry.projects:
            if project.name in seen:
                continue
            projects.append(self._project_to_dict(project))
            seen.add(project.name)
        return ProjectRegistry(projects)

    @classmethod
    def from_registry(cls, *, wiki: LocalLlmWikiAdapter, registry: ProjectRegistry) -> "ProjectKnowledgeResolver":
        cls.bootstrap_registry(wiki, registry)
        return cls(wiki=wiki, fallback=ProjectResolver(registry))

    @staticmethod
    def bootstrap_registry(wiki: LocalLlmWikiAdapter, registry: ProjectRegistry) -> None:
        initializer = ProjectKnowledgeInitializer()
        for project in registry.projects:
            if project.path and Path(project.path).expanduser().is_dir():
                try:
                    initializer.bootstrap_project(wiki, project)
                    continue
                except Exception:
                    # Registry bootstrap must remain a best-effort cache warmup.
                    pass
            wiki.upsert(
                ProjectKnowledgeResolver._project_profile_doc(project),
                options={"dedupe_key": f"project:{project.name}"},
            )

    def resolve(self, text: str, explicit_project: str | None = None) -> ProjectResolveResult:
        wiki_registry = ProjectRegistry([self._project_dict(doc) for doc in self._project_profile_docs()])
        wiki_result = ProjectResolver(wiki_registry).resolve(text, explicit_project=explicit_project)
        if wiki_result.project_path:
            return self._with_wiki_evidence(wiki_result)
        fallback_result = self.fallback.resolve(text, explicit_project=explicit_project)
        if fallback_result.project_path:
            self._upsert_confirmed_profile_from_project(fallback_result.project_name)
        return fallback_result

    def candidate_count_for(self, text: str) -> int:
        result = self.resolve(text)
        if result.project_path:
            return 1
        return len(result.candidates)

    def _project_profile_docs(self) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for ref in self.wiki.find_by_kind("project_profile"):
            doc = self.wiki.read(str(ref.get("id") or ""))
            if not doc or doc.get("status") not in {"verified", "candidate"}:
                continue
            if not self._local_path(doc) or not self._project_name(doc):
                continue
            docs.append(doc)
        return docs

    def _project_dict(self, doc: dict[str, Any]) -> dict[str, Any]:
        modules = doc.get("modules") or []
        module_keywords: list[str] = []
        allowed_paths = list(doc.get("allowed_paths") or [])
        for module in modules:
            if not isinstance(module, dict):
                continue
            module_keywords.extend(str(item) for item in module.get("keywords") or [])
            allowed_paths.extend(str(item) for item in module.get("paths") or [])
        return {
            "name": self._project_name(doc),
            "aliases": [str(item) for item in doc.get("aliases") or []],
            "path": self._local_path(doc),
            "keywords": [str(item) for item in doc.get("keywords") or []] + module_keywords,
            "allowed_paths": allowed_paths,
            "forbidden_paths": [str(item) for item in doc.get("forbidden_paths") or []],
            "default_test_commands": [str(item) for item in doc.get("test_commands") or []],
            "default_runner": doc.get("default_runner"),
        }

    @staticmethod
    def _project_name(doc: dict[str, Any]) -> str:
        return str(doc.get("name") or doc.get("project_id") or doc.get("project") or "")

    @staticmethod
    def _local_path(doc: dict[str, Any]) -> str:
        paths = doc.get("local_paths") or []
        if paths:
            return str(paths[0])
        return str(doc.get("local_path") or doc.get("project_path") or doc.get("path") or "")

    @staticmethod
    def _project_to_dict(project: Project) -> dict[str, Any]:
        return {
            "name": project.name,
            "aliases": list(project.aliases),
            "path": project.path,
            "keywords": list(project.keywords),
            "allowed_paths": list(project.allowed_paths),
            "forbidden_paths": list(project.forbidden_paths),
            "default_test_commands": list(project.default_test_commands),
            "default_runner": project.default_runner,
        }

    @staticmethod
    def _project_profile_doc(project: Project) -> dict[str, Any]:
        return {
            "kind": "project_profile",
            "title": f"{project.name} 项目画像",
            "body": " ".join(
                item
                for item in [
                    project.name,
                    " ".join(project.aliases),
                    " ".join(project.keywords),
                ]
                if item
            ),
            "project": project.name,
            "project_id": project.name,
            "name": project.name,
            "aliases": list(project.aliases),
            "local_paths": [project.path],
            "keywords": list(project.keywords),
            "allowed_paths": list(project.allowed_paths),
            "forbidden_paths": list(project.forbidden_paths),
            "test_commands": list(project.default_test_commands),
            "default_runner": project.default_runner,
            "source_refs": [{"type": "project_registry", "path": "project-registry.json"}],
            "confidence": "high",
            "status": "verified",
        }

    @staticmethod
    def _with_wiki_evidence(result: ProjectResolveResult) -> ProjectResolveResult:
        evidence = [
            MatchEvidence("llm_wiki", item.value, item.score)
            for item in result.match_evidence
        ] or [MatchEvidence("llm_wiki", result.project_name or "", result.confidence)]
        return ProjectResolveResult(
            project_name=result.project_name,
            project_path=result.project_path,
            confidence=result.confidence,
            match_evidence=evidence,
            candidates=result.candidates,
            needs_human=result.needs_human,
        )

    def _upsert_confirmed_profile_from_project(self, project_name: str | None) -> None:
        if not project_name:
            return
        project = self.registry.find_by_name_or_alias(project_name)
        if not isinstance(project, Project):
            return
        self.bootstrap_registry(self.wiki, ProjectRegistry([self._project_to_dict(project)]))
