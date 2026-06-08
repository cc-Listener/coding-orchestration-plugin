from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectInitializationQuality:
    status: str
    has_guidance: bool
    has_project_context: bool
    has_component_contract: bool
    has_verification_commands: bool
    dynamic_source_count: int
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


GUIDANCE_HINTS = (
    "agents.md",
    "claude.md",
    "gemini.md",
    "copilot-instructions.md",
)

PROJECT_CONTEXT_HINTS = (
    "project-map",
    "project_context",
    "project-context",
    "architecture",
    "conventions",
)

COMPONENT_CONTRACT_HINTS = (
    "component-contract",
    "component_contract",
    "contracts/project-context",
    "contracts/project_context",
)


def evaluate_project_initialization_quality(
    *,
    project_path: str | Path | None,
    profile: dict[str, Any] | None,
    dynamic_source_count: int | None = None,
) -> ProjectInitializationQuality:
    profile = profile or {}
    path = Path(project_path).expanduser() if project_path else None
    indexed_docs = _string_list(profile.get("documentation_index"))
    external_sources = _string_list(profile.get("external_sources"))
    test_commands = _string_list(profile.get("test_commands"))

    has_guidance = _matches_any(indexed_docs, GUIDANCE_HINTS) or _project_has_any(path, GUIDANCE_HINTS)
    has_project_context = (
        _matches_any(indexed_docs, PROJECT_CONTEXT_HINTS)
        or bool(profile.get("tech_stack"))
        or _project_has_any(path, PROJECT_CONTEXT_HINTS)
    )
    has_component_contract = _matches_any(indexed_docs, COMPONENT_CONTRACT_HINTS) or _project_has_any(
        path,
        COMPONENT_CONTRACT_HINTS,
    )
    has_verification_commands = bool(test_commands)
    source_count = dynamic_source_count if dynamic_source_count is not None else len(external_sources)

    missing = []
    if not has_guidance:
        missing.append("guidance")
    if not has_project_context:
        missing.append("project_context")
    if not has_component_contract:
        missing.append("component_contract")
    if not has_verification_commands:
        missing.append("verification_commands")

    if not missing:
        status = "complete"
    elif len(missing) < 4 or source_count > 0:
        status = "partial"
    else:
        status = "missing"

    return ProjectInitializationQuality(
        status=status,
        has_guidance=has_guidance,
        has_project_context=has_project_context,
        has_component_contract=has_component_contract,
        has_verification_commands=has_verification_commands,
        dynamic_source_count=source_count,
        missing=missing,
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _matches_any(values: list[str], hints: tuple[str, ...]) -> bool:
    normalized = [value.replace("\\", "/").lower() for value in values]
    return any(any(hint in value for hint in hints) for value in normalized)


def _project_has_any(path: Path | None, hints: tuple[str, ...]) -> bool:
    if path is None or not path.exists() or not path.is_dir():
        return False
    for hint in hints:
        for candidate in _candidate_paths_for_hint(path, hint):
            if _exists_case_insensitive(candidate):
                return True
    return False


def _candidate_paths_for_hint(root: Path, hint: str) -> list[Path]:
    normalized = hint.replace("\\", "/").lower()
    if "/" in normalized:
        return [
            root / normalized,
            root / f"{normalized}.md",
            root / f"{normalized}.yaml",
            root / f"{normalized}.yml",
            root / f"{normalized}.json",
        ]
    return [
        root / normalized,
        root / normalized.upper(),
        root / "docs" / f"{normalized}.md",
        root / "docs" / f"{normalized}.yaml",
        root / "docs" / f"{normalized}.yml",
        root / "contracts" / f"{normalized}.md",
        root / "contracts" / f"{normalized}.yaml",
        root / "contracts" / f"{normalized}.yml",
        root / "contracts" / f"{normalized}.json",
    ]


def _exists_case_insensitive(path: Path) -> bool:
    if path.exists():
        return True
    parent = path.parent
    if not parent.exists() or not parent.is_dir():
        return False
    target = path.name.lower()
    return any(child.name.lower() == target for child in parent.iterdir())
