from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .project_initialization_quality import evaluate_project_initialization_quality
from .project_resolver import Project, normalize_text


class ProjectProfileCatalog:
    def __init__(
        self,
        *,
        wiki: Any,
        registry_projects: Callable[[], Iterable[Project]],
    ) -> None:
        self.wiki = wiki
        self.registry_projects = registry_projects

    def known_profiles(self, limit: int | None = None) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in self.wiki.find_by_kind("project_profile"):
            doc = self.wiki.read(str(ref.get("id") or ""))
            if not doc:
                continue
            profile = self.profile_from_doc(doc)
            name = str(profile.get("name") or "")
            if not name or name in seen:
                continue
            projects.append(profile)
            seen.add(name)
        for project in self.registry_projects():
            if project.name in seen:
                continue
            projects.append(
                {
                    "name": project.name,
                    "project": project.name,
                    "aliases": list(project.aliases),
                    "path": project.path,
                    "status": "registry",
                    "updated_at": "",
                    "source": "project_registry",
                    "dynamic_source_count": 0,
                }
            )
            seen.add(project.name)
        projects.sort(key=lambda item: str(item.get("name") or ""))
        return projects[:limit] if limit else projects

    def find(self, project_name_or_alias: str) -> dict[str, Any] | None:
        target = normalize_text(project_name_or_alias).strip()
        target_key = target.lower()
        for project in self.known_profiles():
            names = [
                str(project.get("name") or ""),
                str(project.get("project") or ""),
                Path(str(project.get("path") or "")).name if project.get("path") else "",
                *[str(item) for item in project.get("aliases") or []],
            ]
            if any(name and normalize_text(name).strip().lower() == target_key for name in names):
                return project
        return None

    def profile_from_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        name = str(doc.get("name") or doc.get("project_id") or doc.get("project") or "").strip()
        paths = doc.get("local_paths") or []
        path = str(paths[0]) if paths else str(doc.get("local_path") or doc.get("project_path") or doc.get("path") or "")
        aliases = [str(item) for item in doc.get("aliases") or [] if str(item).strip()]
        return {
            "name": name,
            "project": str(doc.get("project") or name),
            "aliases": aliases,
            "path": path,
            "status": str(doc.get("status") or "unknown"),
            "updated_at": str(doc.get("updated_at") or ""),
            "source": "llm_wiki",
            "dynamic_source_count": self.dynamic_source_count(name),
            "documentation_index": [str(item) for item in doc.get("documentation_index") or []],
            "external_sources": [str(item) for item in doc.get("external_sources") or []],
            "test_commands": [str(item) for item in doc.get("test_commands") or []],
            "tech_stack": [str(item) for item in doc.get("tech_stack") or []],
            "guarded_paths": [str(item) for item in doc.get("guarded_paths") or []],
            "codex_skills": [str(item) for item in doc.get("codex_skills") or []],
            "codex_agents": [str(item) for item in doc.get("codex_agents") or []],
        }

    def dynamic_source_count(self, project_name: str) -> int:
        if not project_name:
            return 0
        try:
            return len(self.wiki.find_by_kind("external_source_index", filters={"project": project_name}))
        except Exception:
            return 0

    def format_list(self, *, active_project: dict[str, Any] | None) -> str:
        projects = self.known_profiles()
        if not projects:
            return "当前没有已知项目画像。请使用 /coding project init <project_path_or_name> 初始化项目。"
        active_name = str((active_project or {}).get("name") or "")
        lines = ["当前已知项目："]
        for project in projects:
            name = str(project.get("name") or "unknown")
            current = "（当前）" if active_name and name == active_name else ""
            lines.append(f"- {name}{current}")
            lines.append(f"  状态：{project.get('status') or 'unknown'}")
            lines.append(f"  路径: {project.get('path') or '未记录'}")
            aliases = project.get("aliases") or []
            if aliases:
                lines.append(f"  别名: {', '.join(str(item) for item in aliases)}")
            if project.get("updated_at"):
                lines.append(f"  更新时间: {project['updated_at']}")
        return "\n".join(lines)

    def format_status(self, project: dict[str, Any]) -> str:
        dynamic_count = project.get("dynamic_source_count")
        if dynamic_count is None:
            dynamic_count = self.dynamic_source_count(str(project.get("name") or ""))
        quality = evaluate_project_initialization_quality(
            project_path=project.get("path"),
            profile=project,
            dynamic_source_count=dynamic_count,
        )
        missing_labels = {
            "guidance": "项目指导",
            "project_context": "项目上下文",
            "component_contract": "组件/模块合同",
            "verification_commands": "验证命令",
        }
        missing = "无" if not quality.missing else "、".join(missing_labels.get(item, item) for item in quality.missing)
        return "\n".join(
            [
                f"当前项目：{project.get('name') or 'unknown'}",
                f"路径：{project.get('path') or '未记录'}",
                f"初始化状态：{project.get('status') or 'unknown'}",
                f"初始化质量：{quality.status}",
                f"质量门缺口：{missing}",
                f"动态来源索引：{quality.dynamic_source_count} 条",
                f"最近更新时间：{project.get('updated_at') or '未知'}",
            ]
        )
