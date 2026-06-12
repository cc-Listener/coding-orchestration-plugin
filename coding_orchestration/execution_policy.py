from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import RunMode


@dataclass(frozen=True)
class ExecutionPolicy:
    route: str
    planning: str
    context: str
    implementation: str
    verification: str
    allow_browser_qa: bool
    require_human_confirmation: bool
    max_duration_seconds: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def control_policy_for_mode(
    *,
    mode: RunMode | str | None = None,
    codex_decision: Any = None,
) -> ExecutionPolicy:
    del mode
    if not isinstance(codex_decision, dict) or not codex_decision:
        return _missing_decision_policy()

    return ExecutionPolicy(
        route=str(codex_decision.get("route") or "standard_change"),
        planning=str(codex_decision.get("planning") or "plan_only"),
        context=str(codex_decision.get("context") or "project"),
        implementation=str(codex_decision.get("implementation") or "isolated_worktree"),
        verification=str(codex_decision.get("verification") or "standard"),
        allow_browser_qa=_decision_bool(codex_decision.get("allow_browser_qa")),
        require_human_confirmation=_decision_bool(codex_decision.get("require_human_confirmation")),
        max_duration_seconds=_decision_timeout_seconds(codex_decision),
        reasons=["codex_decision"],
    )


def _missing_decision_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        route="standard_change",
        planning="plan_only",
        context="project",
        implementation="isolated_worktree",
        verification="standard",
        allow_browser_qa=False,
        require_human_confirmation=False,
        max_duration_seconds=900,
        reasons=["codex_decision_missing"],
    )


def _decision_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no", ""}:
            return False
    return False


def _decision_timeout_seconds(codex_decision: dict[str, Any]) -> int:
    try:
        value = int(codex_decision.get("max_duration_seconds") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else 900
