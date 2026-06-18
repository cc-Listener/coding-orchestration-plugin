from __future__ import annotations

from typing import Any

from .ports import KnowledgePort
from .project_knowledge_documents import ProjectKnowledgeDocumentBuilder
from .project_knowledge_inventory import ProjectKnowledgeInventory
from .project_resolver import Project


class ProjectKnowledgeInitializer(ProjectKnowledgeDocumentBuilder):
    """Build generic, traceable project knowledge documents for LLM Wiki.

    The initializer stores stable rules and indexes. Dynamic contracts such as
    Swagger/OpenAPI snapshots are indexed as sources and must be re-read before
    implementation.
    """

    def bootstrap_project(self, wiki: KnowledgePort, project: Project) -> list[dict[str, Any]]:
        documents = self.build_documents(project)
        refs: list[dict[str, Any]] = []
        for document in documents:
            refs.append(wiki.upsert(document, options={"dedupe_key": str(document["id"])}))
        return refs


__all__ = [
    "ProjectKnowledgeInitializer",
    "ProjectKnowledgeInventory",
]
