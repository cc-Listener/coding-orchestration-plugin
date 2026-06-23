from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..models import RunMode
from .report_contract import validate_codex_semantic_report


@dataclass(frozen=True)
class ReportAdmissionResult:
    accepted: bool
    report: dict[str, Any]
    reason: str
    errors: list[str]


def admit_report(report: dict[str, Any], mode: RunMode | str) -> ReportAdmissionResult:
    mode_value = mode.value if isinstance(mode, Enum) else str(mode)
    completeness = validate_codex_semantic_report(report, mode_value)
    if not completeness.ok:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason=completeness.reason,
            errors=[f"missing field: {field}" for field in completeness.missing],
        )
    if mode_value == RunMode.DECOMPOSITION.value:
        return _admit_decomposition_report(report)
    return ReportAdmissionResult(accepted=True, report=report, reason="", errors=[])


def _admit_decomposition_report(report: dict[str, Any]) -> ReportAdmissionResult:
    classification = str(report.get("classification") or "")
    open_questions = report.get("open_questions") or []
    materialization_allowed = bool(report.get("materialization_allowed"))
    if materialization_allowed and open_questions:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="materialization_not_allowed_with_open_questions",
            errors=["materialization_allowed=true requires open_questions to be empty"],
        )
    if classification == "needs_clarification" and materialization_allowed:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="clarification_cannot_materialize",
            errors=["classification=needs_clarification requires materialization_allowed=false"],
        )
    known_ids = _known_decomposition_ids(report)
    errors: list[str] = []
    for dependency in report.get("dependencies") or []:
        if not isinstance(dependency, dict):
            errors.append("dependency item must be an object")
            continue
        source = str(dependency.get("from") or dependency.get("source") or "")
        target = str(dependency.get("to") or dependency.get("target") or "")
        if source and source not in known_ids:
            errors.append(f"unknown dependency source: {source}")
        if target and target not in known_ids:
            errors.append(f"unknown dependency target: {target}")
    if errors:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="invalid_decomposition_references",
            errors=errors,
        )
    cycle = _first_cycle(report.get("dependencies") or [])
    if cycle:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="cyclic_decomposition_dependencies",
            errors=[f"dependency cycle: {' -> '.join(cycle)}"],
        )
    return ReportAdmissionResult(accepted=True, report=report, reason="", errors=[])


def _known_decomposition_ids(report: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("delivery_units", "execution_tasks"):
        for item in report.get(key) or []:
            if not isinstance(item, dict):
                continue
            for id_key in ("unit_id", "task_id", "id"):
                value = str(item.get(id_key) or "")
                if value:
                    ids.add(value)
    return ids


def _first_cycle(dependencies: list[Any]) -> list[str]:
    graph: dict[str, list[str]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        source = str(dependency.get("from") or dependency.get("source") or "")
        target = str(dependency.get("to") or dependency.get("target") or "")
        if not source or not target:
            continue
        graph.setdefault(source, []).append(target)
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            start = stack.index(node)
            return stack[start:] + [node]
        if node in visited:
            return []
        visiting.add(node)
        stack.append(node)
        for next_node in graph.get(node, []):
            cycle = visit(next_node)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in graph:
        cycle = visit(node)
        if cycle:
            return cycle
    return []
