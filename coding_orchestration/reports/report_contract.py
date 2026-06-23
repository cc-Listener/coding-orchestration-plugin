from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..models import RunMode


@dataclass(frozen=True)
class ReportCompleteness:
    ok: bool
    missing: list[str]
    reason: str


BASE_REQUIRED_FIELDS = (
    "user_facing_summary",
    "technical_summary",
    "next_actions",
)

DECOMPOSITION_REQUIRED_FIELDS = (
    "classification",
    "reason",
    "delivery_units",
    "execution_tasks",
    "dependencies",
    "risks",
    "acceptance_plan",
    "open_questions",
    "materialization_allowed",
)

MODE_REQUIRED_FIELDS = {
    RunMode.DECOMPOSITION.value: DECOMPOSITION_REQUIRED_FIELDS,
    RunMode.PLAN_ONLY.value: (
        "execution_policy_decision",
        "branch_slug_candidate",
    ),
    RunMode.IMPLEMENTATION.value: (
        "implementation_landed",
        "commit_sha",
        "changed_files_summary",
        "branch_slug_candidate",
        "execution_policy_decision",
    ),
    RunMode.QA.value: (
        "merge_readiness",
    ),
    RunMode.MERGE_TEST.value: (
        "merge_readiness",
    ),
}


def validate_codex_semantic_report(
    report: dict[str, Any], mode: RunMode | str
) -> ReportCompleteness:
    mode_value = mode.value if isinstance(mode, Enum) else str(mode)
    required = [*BASE_REQUIRED_FIELDS, *MODE_REQUIRED_FIELDS.get(mode_value, ())]
    missing = [
        field
        for field in required
        if _is_missing_required_field(report, mode_value=mode_value, field=field)
    ]
    if missing:
        return ReportCompleteness(
            ok=False, missing=missing, reason="codex_report_incomplete"
        )
    return ReportCompleteness(ok=True, missing=[], reason="")


def _is_missing_required_field(
    report: dict[str, Any],
    *,
    mode_value: str,
    field: str,
) -> bool:
    if field not in report:
        return True
    if mode_value == RunMode.DECOMPOSITION.value and field in DECOMPOSITION_REQUIRED_FIELDS:
        value = report.get(field)
        if isinstance(value, str):
            return not value.strip()
        return value is None
    return _is_empty(report.get(field))


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, bool):
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False
