from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    inventory_files: list[str] = field(default_factory=list)
    sensitive_paths: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    package_manager: str | None = None
    package_scripts: dict[str, str] = field(default_factory=dict)
    test_commands: list[str] = field(default_factory=list)
    guarded_paths: list[str] = field(default_factory=list)
    codex_skills: list[str] = field(default_factory=list)
    codex_agents: list[str] = field(default_factory=list)


class ProjectKnowledgeScanner:
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

    def scan(self, root: Path, project: Project) -> ProjectKnowledgeInventory:
        inventory = ProjectKnowledgeInventory(root=root)
        if not root.exists() or not root.is_dir():
            inventory.guarded_paths = self._unique(project.forbidden_paths)
            inventory.test_commands = self._unique(project.default_test_commands)
            return inventory

        files = self._sort_paths(self._iter_project_files(root))
        inventory.inventory_files = self._inventory_file_entries(root, files)
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

    def _iter_project_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for path in root.rglob("*"):
            if any(part in self.SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                files.append(path)
        return files

    def _inventory_file_entries(self, root: Path, files: list[Path]) -> list[str]:
        entries: list[str] = []
        for path in files:
            rel = self._rel(root, path)
            if self._is_sensitive_path(rel):
                entries.append(".env*")
                continue
            entries.append(rel)
        return self._unique(entries)

    def _safe_read_text(self, path: Path) -> str:
        try:
            if path.stat().st_size > self.MAX_TEXT_BYTES:
                return ""
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

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
        if any(hint in lower for hint in ProjectKnowledgeScanner.DYNAMIC_SOURCE_HINTS):
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
