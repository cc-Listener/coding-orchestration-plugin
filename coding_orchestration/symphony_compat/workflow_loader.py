from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WorkflowSpec:
    project_path: str
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    default_test_commands: list[str] = field(default_factory=list)
    plan_required: bool = True
    implementation_allowed: bool = True
    merge_policy: str = "manual_only"
    publish_policy: str = "manual_only"
    recommended_runner: str | None = None
    notes: str = ""


class WorkflowLoader:
    def load(self, project_path: Path) -> WorkflowSpec:
        workflow_path = project_path / "WORKFLOW.md"
        agents_path = project_path / "AGENTS.md"
        codex_agents_path = project_path / ".codex" / "AGENTS.md"
        notes = ""
        text = ""
        if workflow_path.exists():
            text = workflow_path.read_text(encoding="utf-8")
        elif codex_agents_path.exists():
            notes = codex_agents_path.read_text(encoding="utf-8")
        elif agents_path.exists():
            notes = agents_path.read_text(encoding="utf-8")

        sections = self._sections(text)
        return WorkflowSpec(
            project_path=str(project_path),
            allowed_paths=self._list_section(sections, "Allowed Paths"),
            forbidden_paths=self._list_section(sections, "Forbidden Paths"),
            default_test_commands=self._list_section(sections, "Test Commands"),
            merge_policy=self._scalar_section(sections, "Merge Policy", "manual_only"),
            publish_policy=self._scalar_section(sections, "Publish Policy", "manual_only"),
            recommended_runner=self._scalar_section(sections, "Recommended Runner", "") or None,
            notes=notes,
        )

    @staticmethod
    def _sections(text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current: str | None = None
        for line in text.splitlines():
            match = re.match(r"^##\s+(.+?)\s*$", line)
            if match:
                current = match.group(1).strip()
                sections.setdefault(current, [])
                continue
            if current:
                sections[current].append(line)
        return {key: "\n".join(value).strip() for key, value in sections.items()}

    @staticmethod
    def _list_section(sections: dict[str, str], name: str) -> list[str]:
        raw = sections.get(name, "")
        values = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("- "):
                values.append(line[2:].strip())
        return values

    @staticmethod
    def _scalar_section(sections: dict[str, str], name: str, default: str) -> str:
        raw = sections.get(name, "").strip()
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("-"):
                continue
            return line
        return default
