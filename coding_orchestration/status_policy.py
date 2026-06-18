from __future__ import annotations

from typing import Any

from .models import (
    AgentRunStatus,
    RunMode,
    agent_run_status_details,
    apply_failure_type_to_run_details,
)


def status_requires_verification_limitations(status: str) -> bool:
    details = agent_run_status_details(status)
    return run_details_require_verification_limitations(details)


def run_status_details_from_report(
    report: dict[str, Any],
    mode: RunMode,
    *,
    fallback_status: Any = "",
) -> dict[str, Any]:
    source_status = (
        report.get("raw_status")
        or report.get("status_detail")
        or report.get("status")
        or fallback_status
        or "completed_unstructured"
    )
    details = agent_run_status_details(source_status, mode)
    status_detail = str(report.get("status_detail") or "").strip()
    failure_type = str(report.get("failure_type") or "").strip()
    if status_detail:
        details["status_detail"] = status_detail
    if failure_type:
        details = apply_failure_type_to_run_details(details, failure_type)
    if "known_gaps" in report:
        details["known_gaps"] = bool(report.get("known_gaps"))
    if "structured" in report:
        details["structured"] = bool(report.get("structured"))
    if details["known_gaps"] and not details["status_detail"]:
        details["status_detail"] = "ready_for_merge_test_with_known_gaps"
    if details["structured"] is False and not details["status_detail"]:
        details["status_detail"] = "completed_unstructured"
    return details


def run_details_require_verification_limitations(details: dict[str, Any]) -> bool:
    status = str(details.get("status") or "")
    return bool(
        status in {AgentRunStatus.BLOCKED.value, AgentRunStatus.FAILED.value}
        or details.get("known_gaps")
        or details.get("failure_type")
        or details.get("status_detail") in {"completed_unstructured", "ready_for_merge_test_with_known_gaps"}
        or details.get("structured") is False
    )


def run_details_are_runner_failed(details: dict[str, Any]) -> bool:
    return (
        str(details.get("failure_type") or "") == "runner_failed"
        or str(details.get("raw_status") or "") == "runner_failed"
    )


def normalize_implementation_run_status(report: dict[str, Any], mode: RunMode) -> dict[str, Any]:
    details = run_status_details_from_report(report, mode)
    if details.get("structured") is False and mode != RunMode.MERGE_TEST:
        blocked_details = agent_run_status_details("blocked", mode)
        blocked_details["raw_status"] = str(details.get("raw_status") or "")
        blocked_details["status_detail"] = str(details.get("status_detail") or "completed_unstructured")
        blocked_details["structured"] = False
        return blocked_details
    if mode == RunMode.IMPLEMENTATION:
        if report_has_implementation_not_landed_detail(report):
            return _implementation_not_landed_details(mode)
        if not run_details_are_runner_failed(details) and implementation_report_explicitly_not_landed(report):
            return _implementation_not_landed_details(mode)
    if (
        mode == RunMode.IMPLEMENTATION
        and str(details.get("status") or "") == AgentRunStatus.SUCCEEDED.value
        and not details.get("known_gaps")
        and details.get("structured") is not False
        and implementation_report_not_landed(report)
    ):
        return _implementation_not_landed_details(mode)
    return details


def implementation_report_not_landed(report: dict[str, Any]) -> bool:
    if report_has_implementation_not_landed_detail(report):
        return True
    return report.get("implementation_landed") is not True or not str(report.get("commit_sha") or "").strip()


def implementation_report_explicitly_not_landed(report: dict[str, Any]) -> bool:
    if report_has_implementation_not_landed_detail(report):
        return True
    if "implementation_landed" not in report and "commit_sha" not in report:
        return False
    return report.get("implementation_landed") is not True or not str(report.get("commit_sha") or "").strip()


def report_has_implementation_not_landed_detail(report: dict[str, Any]) -> bool:
    return "implementation_not_landed" in {
        str(report.get("failure_type") or ""),
        str(report.get("status_detail") or ""),
    }


def _implementation_not_landed_details(mode: RunMode) -> dict[str, Any]:
    details = agent_run_status_details("blocked", mode)
    details["failure_type"] = "implementation_not_landed"
    details["status_detail"] = "implementation_not_landed"
    return details
