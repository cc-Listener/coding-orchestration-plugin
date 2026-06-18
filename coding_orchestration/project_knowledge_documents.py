from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .project_knowledge_inventory import ProjectKnowledgeInventory, ProjectKnowledgeScanner
from .project_resolver import Project


class ProjectKnowledgeDocumentBuilder(ProjectKnowledgeScanner):
    def build_documents(self, project: Project) -> list[dict[str, Any]]:
        root = Path(project.path).expanduser()
        inventory = self.scan(root, project)
        documents = [self._project_profile_doc(project, inventory)]

        if inventory.guidance_docs or inventory.contract_docs:
            documents.append(self._guidance_doc(project, inventory))
        if inventory.architecture_docs:
            documents.append(self._architecture_doc(project, inventory))
        if inventory.convention_docs:
            documents.append(self._conventions_doc(project, inventory))
        if inventory.tooling_docs or inventory.convention_docs:
            documents.append(self._verification_doc(project, inventory))
            documents.append(self._tooling_doc(project, inventory))
        if inventory.ai_tooling_docs:
            documents.append(self._agent_tooling_doc(project, inventory))
        if inventory.external_source_docs:
            documents.append(self._external_source_index_doc(project, inventory))
        if inventory.historical_plan_docs:
            documents.append(self._historical_plan_index_doc(project, inventory))
        if inventory.guarded_paths or inventory.sensitive_paths:
            documents.append(self._risk_profile_doc(project, inventory))
        return documents

    def _project_profile_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        body_lines = [
            f"项目 `{project.name}` 的初始化画像。",
            "",
            "该页面只作为项目总入口；具体文档、API、历史计划和 agent 配置按需召回。",
            "Codex must classify technology stack, verification commands, and document priority from inventory_files before implementation.",
        ]
        if inventory.guarded_paths:
            body_lines.extend(["", "高风险路径：", *[f"- {item}" for item in inventory.guarded_paths]])
        default_test_commands = list(project.default_test_commands)
        if default_test_commands:
            body_lines.extend(["", "验证入口：", *[f"- {item}" for item in default_test_commands]])
        return {
            "id": f"project:{project.name}",
            "kind": "project_profile",
            "title": f"{project.name} 项目画像",
            "body": "\n".join(body_lines),
            "project": project.name,
            "project_id": project.name,
            "name": project.name,
            "aliases": list(project.aliases),
            "local_paths": [project.path],
            "keywords": list(project.keywords),
            "allowed_paths": list(project.allowed_paths),
            "forbidden_paths": list(project.forbidden_paths),
            "guarded_paths": inventory.guarded_paths,
            "test_commands": default_test_commands,
            "default_runner": project.default_runner,
            "tech_stack": [],
            "inventory_files": inventory.inventory_files,
            "package_manager": inventory.package_manager,
            "documentation_index": [self._rel(inventory.root, path) for path in inventory.markdown_docs],
            "codex_skills": inventory.codex_skills,
            "codex_agents": inventory.codex_agents,
            "external_sources": [self._rel(inventory.root, path) for path in inventory.external_source_docs],
            "source_refs": [
                {"type": "project_registry", "path": "project-registry.json"},
                *self._source_refs(inventory.root, self._profile_source_paths(inventory)),
            ],
            "confidence": "high",
            "status": "verified",
            "freshness": {"mode": "hash_based"},
        }

    def _guidance_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        paths = [*inventory.guidance_docs, *inventory.contract_docs]
        return self._knowledge_doc(
            project,
            inventory,
            doc_id=f"project:{project.name}:guidance",
            kind="project_guidance_contract",
            title=f"{project.name} 项目指导合同",
            paths=paths,
            body_sections=[
                "项目级 agent 指令、machine-readable 合同和 hard stops 的可追溯索引。",
                self._outline_for_sources(inventory.root, paths),
                self._guarded_paths_section(inventory),
            ],
            status="verified",
            confidence="high",
        )

    def _architecture_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        return self._knowledge_doc(
            project,
            inventory,
            doc_id=f"project:{project.name}:architecture",
            kind="project_architecture_map",
            title=f"{project.name} 架构地图",
            paths=inventory.architecture_docs,
            body_sections=[
                "项目结构、模块边界和主要入口的索引。",
                self._outline_for_sources(inventory.root, inventory.architecture_docs),
            ],
            status="verified",
            confidence="high",
        )

    def _conventions_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        return self._knowledge_doc(
            project,
            inventory,
            doc_id=f"project:{project.name}:conventions",
            kind="project_conventions",
            title=f"{project.name} 开发约定",
            paths=inventory.convention_docs,
            body_sections=[
                "编码规范、组件契约、接口接入规则和协作约定的索引。",
                self._outline_for_sources(inventory.root, inventory.convention_docs),
            ],
            status="verified",
            confidence="high",
        )

    def _verification_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        sections = ["验证命令和测试现状索引。"]
        if inventory.test_commands:
            sections.append("\n".join(["推荐验证命令：", *[f"- {item}" for item in inventory.test_commands]]))
        else:
            sections.append("未从项目脚本或 registry 中识别到稳定验证命令。")
        return self._knowledge_doc(
            project,
            inventory,
            doc_id=f"project:{project.name}:verification",
            kind="verification_profile",
            title=f"{project.name} 验证画像",
            paths=[*inventory.tooling_docs, *inventory.convention_docs],
            body_sections=sections,
            status="verified",
            confidence="high",
        )

    def _tooling_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        sections = ["工程工具、包管理器和脚本索引。"]
        if inventory.package_manager:
            sections.append(f"包管理器：`{inventory.package_manager}`")
        if inventory.tech_stack:
            sections.append("\n".join(["技术栈：", *[f"- {item}" for item in inventory.tech_stack]]))
        if inventory.package_scripts:
            sections.append(
                "\n".join(["package scripts：", *[f"- {name}: {cmd}" for name, cmd in inventory.package_scripts.items()]])
            )
        return self._knowledge_doc(
            project,
            inventory,
            doc_id=f"project:{project.name}:tooling",
            kind="tooling_profile",
            title=f"{project.name} 工程工具画像",
            paths=inventory.tooling_docs,
            body_sections=sections,
            status="verified",
            confidence="high",
        )

    def _agent_tooling_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        sections = ["项目内 AI agent、Codex skill 和相邻工具配置索引。"]
        if inventory.codex_skills:
            sections.append("\n".join(["项目 skills：", *[f"- {item}" for item in inventory.codex_skills]]))
        if inventory.codex_agents:
            sections.append("\n".join(["项目 agents：", *[f"- {item}" for item in inventory.codex_agents]]))
        sections.append(self._outline_for_sources(inventory.root, inventory.ai_tooling_docs))
        return self._knowledge_doc(
            project,
            inventory,
            doc_id=f"project:{project.name}:agent-tooling",
            kind="agent_tooling_profile",
            title=f"{project.name} Agent 工具画像",
            paths=inventory.ai_tooling_docs,
            body_sections=sections,
            status="verified",
            confidence="high",
        )

    def _external_source_index_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        body = "\n".join(
            [
                "动态外部契约来源索引。",
                "",
                "这些来源可能过期，不能把其中的 endpoint、字段、schema 或 enum 当成长期 verified 知识。",
                "涉及接口、设计稿、飞书需求或外部文档时，必须在当前任务中重新读取源文件或链接。",
                "",
                "来源：",
                *[f"- {self._rel(inventory.root, path)}" for path in inventory.external_source_docs],
            ]
        )
        return {
            "id": f"project:{project.name}:external-sources",
            "kind": "external_source_index",
            "title": f"{project.name} 动态来源索引",
            "body": body,
            "project": project.name,
            "module": None,
            "tags": ["project", "external_source", "dynamic_contract"],
            "source_refs": self._source_refs(inventory.root, inventory.external_source_docs),
            "confidence": "medium",
            "status": "candidate",
            "freshness": {
                "mode": "read_before_use",
                "stale_after": "0s",
            },
        }

    def _historical_plan_index_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        body = "\n".join(
            [
                "历史计划和决策记录索引。",
                "",
                "这些内容只用于按关键词召回相似方案，默认不作为当前实现事实。",
                "",
                *self._historical_plan_lines(inventory.root, inventory.historical_plan_docs),
            ]
        )
        return {
            "id": f"project:{project.name}:historical-plans",
            "kind": "historical_plan_index",
            "title": f"{project.name} 历史计划索引",
            "body": body,
            "project": project.name,
            "module": None,
            "tags": ["project", "historical_plan"],
            "source_refs": self._source_refs(inventory.root, inventory.historical_plan_docs),
            "confidence": "medium",
            "status": "candidate",
            "freshness": {"mode": "hash_based"},
        }

    def _risk_profile_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        sections = ["高风险路径、敏感入口和审批边界索引。", self._guarded_paths_section(inventory)]
        if inventory.sensitive_paths:
            sections.append("敏感入口只记录存在性，不读取内容：\n" + "\n".join(f"- {item}" for item in inventory.sensitive_paths))
        return self._knowledge_doc(
            project,
            inventory,
            doc_id=f"project:{project.name}:risk",
            kind="risk_profile",
            title=f"{project.name} 风险画像",
            paths=[*inventory.guidance_docs, *inventory.contract_docs],
            body_sections=sections,
            status="verified",
            confidence="high",
        )

    def _knowledge_doc(
        self,
        project: Project,
        inventory: ProjectKnowledgeInventory,
        *,
        doc_id: str,
        kind: str,
        title: str,
        paths: list[Path],
        body_sections: list[str],
        status: str,
        confidence: str,
    ) -> dict[str, Any]:
        return {
            "id": doc_id,
            "kind": kind,
            "title": title,
            "body": "\n\n".join(section for section in body_sections if section),
            "project": project.name,
            "module": None,
            "tags": ["project", kind],
            "source_refs": self._source_refs(inventory.root, paths),
            "confidence": confidence,
            "status": status,
            "freshness": {"mode": "hash_based"},
        }

    def _profile_source_paths(self, inventory: ProjectKnowledgeInventory) -> list[Path]:
        return self._sort_paths(
            [
                *inventory.guidance_docs,
                *inventory.contract_docs,
                *inventory.architecture_docs,
                *inventory.convention_docs,
                *inventory.tooling_docs,
                *inventory.ai_tooling_docs,
                *inventory.external_source_docs,
            ]
        )

    def _source_refs(self, root: Path, paths: list[Path]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in paths:
            if not path.exists() or not path.is_file():
                continue
            rel = self._rel(root, path)
            if rel in seen:
                continue
            seen.add(rel)
            stat = path.stat()
            refs.append(
                {
                    "type": self._source_type(rel),
                    "path": rel,
                    "sha256": self._sha256(path),
                    "mtime": int(stat.st_mtime),
                    "size": stat.st_size,
                }
            )
        return refs

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _outline_for_sources(self, root: Path, paths: list[Path]) -> str:
        lines: list[str] = ["来源大纲："]
        for path in paths:
            rel = self._rel(root, path)
            text = self._safe_read_text(path)
            headings = self._markdown_headings(text)
            if headings:
                lines.append(f"- {rel}: " + " / ".join(headings[:8]))
                continue
            title = self._first_non_empty_line(text)
            lines.append(f"- {rel}" + (f": {title[:120]}" if title else ""))
        return "\n".join(lines)

    def _historical_plan_lines(self, root: Path, paths: list[Path]) -> list[str]:
        lines: list[str] = []
        for path in paths:
            rel = self._rel(root, path)
            text = self._safe_read_text(path)
            title = self._first_markdown_title(text) or path.stem
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", rel)
            date = date_match.group(1) if date_match else ""
            prefix = f"- {date} " if date else "- "
            lines.append(f"{prefix}{title} (`{rel}`)")
        return lines

    @staticmethod
    def _markdown_headings(text: str) -> list[str]:
        headings: list[str] = []
        for line in text.splitlines():
            match = re.match(r"^\s{0,3}#{1,4}\s+(.+?)\s*$", line)
            if match:
                headings.append(match.group(1).strip())
        return headings

    def _first_markdown_title(self, text: str) -> str | None:
        headings = self._markdown_headings(text)
        return headings[0] if headings else None

    @staticmethod
    def _first_non_empty_line(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return ""

    def _guarded_paths_section(self, inventory: ProjectKnowledgeInventory) -> str:
        if not inventory.guarded_paths:
            return "未识别到明确 guarded paths。"
        return "\n".join(["guarded paths：", *[f"- {item}" for item in inventory.guarded_paths]])
