from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import AgentRunStatus, RunMode, agent_run_status_details
from ...policies.status_policy import normalize_implementation_run_status, run_status_details_from_report


@dataclass(frozen=True)
class BlockedReportProjection:
    status: str
    details: dict[str, Any]
    report: dict[str, Any]


@dataclass(frozen=True)
class RunReportRefinement:
    status: str
    details: dict[str, Any]
    report: dict[str, Any]
    requires_implementation_commit_check: bool


def _list_report_field(report: dict[str, Any], field: str) -> list[Any]:
    value = report.get(field)
    return list(value) if isinstance(value, list) else []


def build_diff_guard_blocked_report(
    report: dict[str, Any],
    *,
    mode: RunMode,
    violations: list[str],
    diff_path: Any,
) -> BlockedReportProjection:
    details = agent_run_status_details("blocked", mode)
    blocked_report = dict(report)
    blocked_report.update(details)
    blocked_report["human_required"] = True
    blocked_report["risks"] = _list_report_field(blocked_report, "risks") + list(violations)
    blocked_report["verification_limitations"] = _list_report_field(
        blocked_report, "verification_limitations"
    ) + [
        {
            "reason": "diff_guard_violation",
            "impact": "The run modified files outside the allowed workflow boundary, so Hermes cannot mark it safe.",
            "recovery_action": "Review diff.patch and rerun after constraining edits to allowed paths or explicitly approving the path change.",
            "fallback_evidence": str(diff_path),
        }
    ]
    blocked_report["next_actions"] = _list_report_field(blocked_report, "next_actions") + [
        "人工检查越权 diff，确认是否丢弃或重跑。"
    ]
    return BlockedReportProjection(status=str(details["status"]), details=details, report=blocked_report)


def build_implementation_commit_missing_report(
    report: dict[str, Any],
    *,
    mode: RunMode,
    diff_path: Any,
) -> BlockedReportProjection:
    details = agent_run_status_details("blocked", mode)
    blocked_report = dict(report)
    blocked_report.update(details)
    blocked_report["human_required"] = True
    blocked_report["risks"] = _list_report_field(blocked_report, "risks") + [
        "implementation 已返回成功，但 Codex 未提交本次实现改动，不能安全进入 QA 或 merge-test。"
    ]
    blocked_report["verification_limitations"] = _list_report_field(
        blocked_report, "verification_limitations"
    ) + [
        {
            "reason": "implementation_commit_missing",
            "impact": "Implementation changes remain uncommitted in the task workspace, so downstream QA/merge-test would not have a stable source commit.",
            "recovery_action": "让 Codex 依据实际 diff 按 Git Flow/Conventional Commit 规范创建提交，或重新触发 implementation 完成提交后再继续。",
            "fallback_evidence": str(diff_path),
        }
    ]
    blocked_report["next_actions"] = _list_report_field(blocked_report, "next_actions") + [
        "让 Codex 提交当前 implementation 改动后，再重新触发 QA 或 merge-test。"
    ]
    return BlockedReportProjection(status=str(details["status"]), details=details, report=blocked_report)


def refine_run_report_projection(
    report: dict[str, Any],
    *,
    mode: RunMode,
    fallback_status: Any = "",
    violations: list[str],
    diff_path: Any,
    implementation_commit_missing: bool = False,
) -> RunReportRefinement:
    projected_report = dict(report)
    details = run_status_details_from_report(projected_report, mode, fallback_status=fallback_status)
    projected_report.update(details)
    if violations:
        blocked = build_diff_guard_blocked_report(
            projected_report,
            mode=mode,
            violations=violations,
            diff_path=diff_path,
        )
        return RunReportRefinement(
            status=blocked.status,
            details=blocked.details,
            report=blocked.report,
            requires_implementation_commit_check=False,
        )

    details = normalize_implementation_run_status(projected_report, mode)
    status = str(details["status"])
    projected_report.update(details)
    requires_implementation_commit_check = (
        mode == RunMode.IMPLEMENTATION and status == AgentRunStatus.SUCCEEDED.value
    )
    if implementation_commit_missing and requires_implementation_commit_check:
        blocked = build_implementation_commit_missing_report(
            projected_report,
            mode=mode,
            diff_path=diff_path,
        )
        return RunReportRefinement(
            status=blocked.status,
            details=blocked.details,
            report=blocked.report,
            requires_implementation_commit_check=False,
        )
    return RunReportRefinement(
        status=status,
        details=details,
        report=projected_report,
        requires_implementation_commit_check=requires_implementation_commit_check,
    )
