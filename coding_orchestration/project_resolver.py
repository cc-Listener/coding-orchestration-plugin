from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import MatchEvidence, ProjectCandidate, ProjectResolveResult


@dataclass(frozen=True)
class Project:
    name: str
    path: str
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    default_test_commands: tuple[str, ...] = ()
    default_runner: str | None = None


class ProjectRegistry:
    def __init__(self, projects: list[dict[str, Any]] | None = None):
        self.projects = [self._coerce_project(p) for p in (projects or [])]

    @classmethod
    def from_file(cls, path: Path) -> "ProjectRegistry":
        if not path.exists():
            return cls([])
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("projects", []))

    @staticmethod
    def _coerce_project(data: dict[str, Any]) -> Project:
        return Project(
            name=str(data["name"]),
            path=str(data["path"]),
            aliases=tuple(str(x) for x in data.get("aliases", [])),
            keywords=tuple(str(x) for x in data.get("keywords", [])),
            allowed_paths=tuple(str(x) for x in data.get("allowed_paths", [])),
            forbidden_paths=tuple(str(x) for x in data.get("forbidden_paths", [])),
            default_test_commands=tuple(str(x) for x in data.get("default_test_commands", [])),
            default_runner=data.get("default_runner"),
        )

    def find_by_name_or_alias(self, value: str) -> Project | None:
        needle = normalize_text(value).strip().lower()
        for project in self.projects:
            if normalize_text(project.name).lower() == needle:
                return project
            if any(normalize_text(alias).lower() == needle for alias in project.aliases):
                return project
        return None


def normalize_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>])", r"\1", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"[ \t]+", " ", text).strip()


class ProjectResolver:
    AUTO_ROUTE_THRESHOLD = 0.8
    HUMAN_REVIEW_THRESHOLD = 0.5
    AMBIGUITY_GAP = 0.15

    def __init__(self, registry: ProjectRegistry):
        self.registry = registry

    def resolve(self, text: str, explicit_project: str | None = None) -> ProjectResolveResult:
        source_text = normalize_text(text)
        if explicit_project:
            project = self.registry.find_by_name_or_alias(explicit_project)
            if project:
                return self._result(
                    project,
                    confidence=1.0,
                    evidence=[MatchEvidence("explicit", explicit_project, 1.0)],
                    needs_human=False,
                )
            return ProjectResolveResult(
                project_name=None,
                project_path=None,
                confidence=0.0,
                match_evidence=[MatchEvidence("explicit", explicit_project, 0.0)],
                candidates=[],
                needs_human=True,
            )

        exact_matches: list[tuple[Project, MatchEvidence]] = []
        lowered = source_text.lower()
        for project in self.registry.projects:
            if normalize_text(project.name).lower() in lowered:
                exact_matches.append((project, MatchEvidence("name", project.name, 0.95)))
            for alias in project.aliases:
                if normalize_text(alias).lower() in lowered:
                    exact_matches.append((project, MatchEvidence("alias", alias, 0.9)))

        unique_exact = self._unique_projects(exact_matches)
        if len(unique_exact) == 1:
            project, evidence = unique_exact[0]
            return self._result(project, confidence=evidence.score, evidence=[evidence], needs_human=False)
        if len(unique_exact) > 1:
            return self._ambiguous(unique_exact)

        scored: list[tuple[Project, float, list[MatchEvidence]]] = []
        for project in self.registry.projects:
            evidence: list[MatchEvidence] = []
            score = 0.0
            for keyword in project.keywords:
                if keyword and keyword.lower() in lowered:
                    score += 0.35
                    evidence.append(MatchEvidence("keyword", keyword, 0.35))
            if score > 0:
                scored.append((project, min(score, 0.79), evidence))

        scored.sort(key=lambda item: item[1], reverse=True)
        if not scored:
            return ProjectResolveResult(None, None, 0.0, [], [], True)

        candidates = [
            ProjectCandidate(project.name, project.path, confidence)
            for project, confidence, _ in scored
        ]
        if len(scored) > 1 and scored[0][1] - scored[1][1] < self.AMBIGUITY_GAP:
            return ProjectResolveResult(None, None, scored[0][1], scored[0][2], candidates, True)

        project, confidence, evidence = scored[0]
        if confidence >= self.AUTO_ROUTE_THRESHOLD:
            return self._result(project, confidence, evidence, False)
        return ProjectResolveResult(None, None, confidence, evidence, candidates, True)

    @staticmethod
    def _unique_projects(items: list[tuple[Project, MatchEvidence]]) -> list[tuple[Project, MatchEvidence]]:
        seen: set[str] = set()
        result: list[tuple[Project, MatchEvidence]] = []
        for project, evidence in items:
            if project.name in seen:
                continue
            seen.add(project.name)
            result.append((project, evidence))
        return result

    @staticmethod
    def _result(
        project: Project,
        confidence: float,
        evidence: list[MatchEvidence],
        needs_human: bool,
    ) -> ProjectResolveResult:
        return ProjectResolveResult(
            project_name=project.name,
            project_path=project.path,
            confidence=confidence,
            match_evidence=evidence,
            candidates=[ProjectCandidate(project.name, project.path, confidence)],
            needs_human=needs_human,
        )

    @staticmethod
    def _ambiguous(items: list[tuple[Project, MatchEvidence]]) -> ProjectResolveResult:
        candidates = [ProjectCandidate(project.name, project.path, evidence.score) for project, evidence in items]
        return ProjectResolveResult(
            project_name=None,
            project_path=None,
            confidence=max((c.confidence for c in candidates), default=0.0),
            match_evidence=[evidence for _, evidence in items],
            candidates=candidates,
            needs_human=True,
        )
