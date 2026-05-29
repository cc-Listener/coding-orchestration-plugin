from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm_wiki_adapter import LocalLlmWikiAdapter
from .project_resolver import Project


@dataclass
class ProjectKnowledgeInventory:
    root: Path
    markdown_docs: list[Path] = field(default_factory=list)
    guidance_docs: list[Path] = field(default_factory=list)
    contract_docs: list[Path] = field(default_factory=list)
    architecture_docs: list[Path] = field(default_factory=list)
    convention_docs: list[Path] = field(default_factory=list)
    historical_plan_docs: list[Path] = field(default_factory=list)
    ai_tooling_docs: list[Path] = field(default_factory=list)
    tooling_docs: list[Path] = field(default_factory=list)
    external_source_docs: list[Path] = field(default_factory=list)
    sensitive_paths: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    package_manager: str | None = None
    package_scripts: dict[str, str] = field(default_factory=dict)
    test_commands: list[str] = field(default_factory=list)
    guarded_paths: list[str] = field(default_factory=list)
    codex_skills: list[str] = field(default_factory=list)
    codex_agents: list[str] = field(default_factory=list)


class ProjectKnowledgeInitializer:
    """Build generic, traceable project knowledge documents for LLM Wiki.

    The initializer stores stable rules and indexes. Dynamic contracts such as
    Swagger/OpenAPI snapshots are indexed as sources and must be re-read before
    implementation.
    """

    MAX_TEXT_BYTES = 512 * 1024
    SKIP_DIRS = {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "coverage",
        ".turbo",
        ".cache",
        ".pytest_cache",
        "__pycache__",
        "vendor",
    }
    GUIDANCE_FILES = {
        "agents.md",
        "claude.md",
        "gemini.md",
        "copilot-instructions.md",
    }
    TOOLING_FILES = {
        "package.json",
        "pnpm-workspace.yaml",
        "turbo.json",
        "nx.json",
        "vite.config.ts",
        "vite.config.js",
        "vite.config.mts",
        "tsconfig.json",
        "pyproject.toml",
        "pytest.ini",
        "cargo.toml",
        "go.mod",
        "makefile",
    }
    DYNAMIC_SOURCE_HINTS = (
        "api-spec",
        ".api-spec",
        "openapi",
        "swagger",
        "apifox",
        "figma",
        "feishu",
        "lark",
    )

    def bootstrap_project(self, wiki: LocalLlmWikiAdapter, project: Project) -> list[dict[str, Any]]:
        documents = self.build_documents(project)
        refs: list[dict[str, Any]] = []
        for document in documents:
            refs.append(wiki.upsert(document, options={"dedupe_key": str(document["id"])}))
        return refs

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

    def scan(self, root: Path, project: Project) -> ProjectKnowledgeInventory:
        inventory = ProjectKnowledgeInventory(root=root)
        if not root.exists() or not root.is_dir():
            inventory.guarded_paths = self._unique(project.forbidden_paths)
            inventory.test_commands = self._unique(project.default_test_commands)
            return inventory

        files = list(self._iter_project_files(root))
        for path in files:
            rel = self._rel(root, path)
            lower_rel = rel.lower()
            name = path.name.lower()
            suffix = path.suffix.lower()

            if self._is_sensitive_path(rel):
                if ".env*" not in inventory.sensitive_paths:
                    inventory.sensitive_paths.append(".env*")
                continue

            if suffix in {".md", ".markdown", ".mdx", ".mdc"}:
                inventory.markdown_docs.append(path)
            if self._is_guidance_file(rel, name):
                inventory.guidance_docs.append(path)
            if lower_rel.startswith("contracts/") and suffix in {".yaml", ".yml", ".json", ".toml", ".md"}:
                inventory.contract_docs.append(path)
            if self._is_architecture_doc(lower_rel):
                inventory.architecture_docs.append(path)
            if self._is_convention_doc(lower_rel):
                inventory.convention_docs.append(path)
            if self._is_historical_plan_doc(lower_rel):
                inventory.historical_plan_docs.append(path)
            if self._is_ai_tooling_doc(lower_rel, suffix):
                inventory.ai_tooling_docs.append(path)
            if self._is_tooling_doc(name, lower_rel):
                inventory.tooling_docs.append(path)
            if self._is_external_source_doc(lower_rel):
                inventory.external_source_docs.append(path)

        inventory.markdown_docs = self._sort_paths(inventory.markdown_docs)
        inventory.guidance_docs = self._sort_paths(inventory.guidance_docs)
        inventory.contract_docs = self._sort_paths(inventory.contract_docs)
        inventory.architecture_docs = self._sort_paths(inventory.architecture_docs)
        inventory.convention_docs = self._sort_paths(inventory.convention_docs)
        inventory.historical_plan_docs = self._sort_paths(inventory.historical_plan_docs)
        inventory.ai_tooling_docs = self._sort_paths(inventory.ai_tooling_docs)
        inventory.tooling_docs = self._sort_paths(inventory.tooling_docs)
        inventory.external_source_docs = self._sort_paths(inventory.external_source_docs)

        inventory.package_manager = self._detect_package_manager(root)
        inventory.package_scripts = self._read_package_scripts(root / "package.json")
        inventory.tech_stack = self._infer_tech_stack(root)
        inventory.test_commands = self._unique(
            [*project.default_test_commands, *self._commands_from_scripts(inventory)]
        )
        inventory.codex_skills = self._codex_skills(root, inventory.ai_tooling_docs)
        inventory.codex_agents = self._codex_agents(root, inventory.ai_tooling_docs)
        inventory.guarded_paths = self._unique(
            [
                *project.forbidden_paths,
                *self._extract_guarded_paths(root, inventory.guidance_docs, inventory.contract_docs),
                *inventory.sensitive_paths,
            ]
        )
        return inventory

    def _project_profile_doc(self, project: Project, inventory: ProjectKnowledgeInventory) -> dict[str, Any]:
        body_lines = [
            f"项目 `{project.name}` 的初始化画像。",
            "",
            "该页面只作为项目总入口；具体文档、API、历史计划和 agent 配置按需召回。",
        ]
        if inventory.tech_stack:
            body_lines.extend(["", "技术栈：", *[f"- {item}" for item in inventory.tech_stack]])
        if inventory.guarded_paths:
            body_lines.extend(["", "高风险路径：", *[f"- {item}" for item in inventory.guarded_paths]])
        if inventory.test_commands:
            body_lines.extend(["", "验证入口：", *[f"- {item}" for item in inventory.test_commands]])
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
            "test_commands": inventory.test_commands,
            "default_runner": project.default_runner,
            "tech_stack": inventory.tech_stack,
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

    def _iter_project_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for path in root.rglob("*"):
            if any(part in self.SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                files.append(path)
        return files

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

    def _safe_read_text(self, path: Path) -> str:
        try:
            if path.stat().st_size > self.MAX_TEXT_BYTES:
                return ""
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

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

    def _extract_guarded_paths(self, root: Path, guidance_docs: list[Path], contract_docs: list[Path]) -> list[str]:
        paths: list[str] = []
        for doc in [*guidance_docs, *contract_docs]:
            text = self._safe_read_text(doc)
            paths.extend(self._extract_path_mentions(text))
            if "guarded_paths" in text:
                paths.extend(self._extract_yaml_path_values(text))
        return self._unique(paths)

    @staticmethod
    def _extract_path_mentions(text: str) -> list[str]:
        paths: list[str] = []
        for value in re.findall(r"`([^`]+)`", text):
            if "/" not in value and not value.startswith(".env"):
                continue
            if re.search(r"\s", value):
                continue
            paths.append(value)
        return paths

    @staticmethod
    def _extract_yaml_path_values(text: str) -> list[str]:
        values: list[str] = []
        for line in text.splitlines():
            match = re.match(r"\s*-\s*path:\s*(.+?)\s*$", line) or re.match(r"\s*path:\s*(.+?)\s*$", line)
            if match:
                value = match.group(1).strip().strip("'\"")
                if value:
                    values.append(value)
        return values

    @staticmethod
    def _detect_package_manager(root: Path) -> str | None:
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (root / "yarn.lock").exists():
            return "yarn"
        if (root / "package-lock.json").exists():
            return "npm"
        if (root / "package.json").exists():
            return "npm"
        if (root / "pyproject.toml").exists():
            return "python"
        if (root / "Cargo.toml").exists():
            return "cargo"
        if (root / "go.mod").exists():
            return "go"
        return None

    def _read_package_scripts(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        scripts = data.get("scripts")
        if not isinstance(scripts, dict):
            return {}
        return {str(key): str(value) for key, value in sorted(scripts.items())}

    def _commands_from_scripts(self, inventory: ProjectKnowledgeInventory) -> list[str]:
        package_manager = inventory.package_manager or "npm"
        commands: list[str] = []
        for name in inventory.package_scripts:
            lowered = name.lower()
            if not (
                lowered == "test"
                or lowered.startswith("test")
                or "lint" in lowered
                or "build" in lowered
                or "typecheck" in lowered
                or "format" in lowered
                or "check" in lowered
            ):
                continue
            if package_manager == "pnpm":
                commands.append(f"rtk pnpm {name}")
            elif package_manager == "yarn":
                commands.append(f"rtk yarn {name}")
            elif package_manager == "npm":
                commands.append(f"rtk npm run {name}")
        return commands

    def _infer_tech_stack(self, root: Path) -> list[str]:
        stack: list[str] = []
        package_json = root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            deps = {
                **(data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}),
                **(data.get("devDependencies") if isinstance(data.get("devDependencies"), dict) else {}),
            }
            package_map = [
                ("react", "React"),
                ("vue", "Vue"),
                ("@angular/core", "Angular"),
                ("next", "Next.js"),
                ("vite", "Vite"),
                ("typescript", "TypeScript"),
                ("mobx", "MobX"),
                ("antd", "Ant Design"),
                ("@refinedev/core", "Refine"),
            ]
            for package_name, label in package_map:
                if package_name in deps:
                    stack.append(label)
        if (root / "pyproject.toml").exists():
            stack.append("Python")
        if (root / "Cargo.toml").exists():
            stack.append("Rust")
        if (root / "go.mod").exists():
            stack.append("Go")
        return self._unique(stack)

    def _codex_skills(self, root: Path, paths: list[Path]) -> list[str]:
        skills: list[str] = []
        for path in paths:
            rel = self._rel(root, path)
            lower = rel.lower()
            if lower.endswith("/skill.md"):
                skills.append(rel)
        return self._unique(skills)

    def _codex_agents(self, root: Path, paths: list[Path]) -> list[str]:
        agents: list[str] = []
        for path in paths:
            rel = self._rel(root, path)
            lower = rel.lower()
            if "/agents/" in lower or lower.endswith("agents.md"):
                agents.append(rel)
        return self._unique(agents)

    def _is_guidance_file(self, rel: str, name: str) -> bool:
        lower_rel = rel.lower()
        return (
            name in self.GUIDANCE_FILES
            or lower_rel.startswith(".cursor/rules")
            or lower_rel.startswith(".github/copilot-instructions")
        )

    @staticmethod
    def _is_architecture_doc(lower_rel: str) -> bool:
        name = Path(lower_rel).name
        return any(
            hint in name
            for hint in [
                "project-map",
                "architecture",
                "arch",
                "structure",
                "component-contract",
            ]
        )

    @staticmethod
    def _is_convention_doc(lower_rel: str) -> bool:
        name = Path(lower_rel).name
        return any(
            hint in name
            for hint in [
                "convention",
                "conventions",
                "contributing",
                "guideline",
                "style",
                "api-integration",
            ]
        )

    @staticmethod
    def _is_historical_plan_doc(lower_rel: str) -> bool:
        return lower_rel.startswith("docs/plans/") or lower_rel.startswith("adr/") or lower_rel.startswith("decisions/")

    @staticmethod
    def _is_ai_tooling_doc(lower_rel: str, suffix: str) -> bool:
        if not lower_rel.startswith((".codex/", ".agents/", "skills/")):
            return False
        return suffix in {".md", ".toml", ".yaml", ".yml", ".json"} or lower_rel.endswith("/skill.md")

    def _is_tooling_doc(self, name: str, lower_rel: str) -> bool:
        return name in self.TOOLING_FILES or lower_rel.startswith(".github/workflows/")

    def _is_external_source_doc(self, lower_rel: str) -> bool:
        if "api-integration" in lower_rel:
            return False
        suffix = Path(lower_rel).suffix.lower()
        if suffix not in {".md", ".json", ".yaml", ".yml", ".toml", ".txt"}:
            return False
        return any(hint in lower_rel for hint in self.DYNAMIC_SOURCE_HINTS)

    @staticmethod
    def _is_sensitive_path(rel: str) -> bool:
        name = Path(rel).name
        return name == ".env" or name.startswith(".env.")

    @staticmethod
    def _source_type(rel: str) -> str:
        lower = rel.lower()
        if lower.startswith(".codex/") or lower.startswith(".agents/") or lower.startswith("skills/"):
            return "agent_tooling"
        if lower.startswith("contracts/"):
            return "project_contract"
        if lower.startswith("docs/plans/") or lower.startswith("adr/") or lower.startswith("decisions/"):
            return "historical_plan"
        if any(hint in lower for hint in ProjectKnowledgeInitializer.DYNAMIC_SOURCE_HINTS):
            return "external_source"
        if lower.endswith(".md") or lower.endswith(".mdx") or lower.endswith(".mdc"):
            return "markdown"
        return "project_file"

    @staticmethod
    def _rel(root: Path, path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def _sort_paths(paths: list[Path]) -> list[Path]:
        return sorted({path for path in paths}, key=lambda item: item.as_posix())

    @staticmethod
    def _unique(values: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result
