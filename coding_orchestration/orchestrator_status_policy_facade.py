from __future__ import annotations

from typing import Any

from . import run_orchestration_service, status_policy
from .models import ArtifactSet, RunMode, TaskPhase, TaskStatus
from .services import RunService


class OrchestratorStatusPolicyFacadeMixin:
    @staticmethod
    def _status_requires_verification_limitations(status: str) -> bool:
        return status_policy.status_requires_verification_limitations(status)

    @staticmethod
    def _run_status_details_from_report(
        report: dict[str, Any],
        mode: RunMode,
        *,
        fallback_status: Any = "",
    ) -> dict[str, Any]:
        return status_policy.run_status_details_from_report(report, mode, fallback_status=fallback_status)

    @staticmethod
    def _run_details_require_verification_limitations(details: dict[str, Any]) -> bool:
        return status_policy.run_details_require_verification_limitations(details)

    @staticmethod
    def _run_details_are_runner_failed(details: dict[str, Any]) -> bool:
        return status_policy.run_details_are_runner_failed(details)

    @staticmethod
    def _normalize_implementation_run_status(report: dict[str, Any], mode: RunMode) -> dict[str, Any]:
        return status_policy.normalize_implementation_run_status(report, mode)

    @staticmethod
    def _implementation_report_not_landed(report: dict[str, Any]) -> bool:
        return status_policy.implementation_report_not_landed(report)

    @staticmethod
    def _implementation_report_explicitly_not_landed(report: dict[str, Any]) -> bool:
        return status_policy.implementation_report_explicitly_not_landed(report)

    @staticmethod
    def _report_has_implementation_not_landed_detail(report: dict[str, Any]) -> bool:
        return status_policy.report_has_implementation_not_landed_detail(report)

    def _ensure_verification_limitations(
        self,
        report: dict[str, Any],
        status: str,
        artifacts: ArtifactSet,
    ) -> dict[str, Any]:
        return run_orchestration_service.ensure_verification_limitations(
            report,
            status=status,
            stdout_path=artifacts.stdout,
            stderr_path=artifacts.stderr,
        )

    @staticmethod
    def _task_status_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskStatus:
        return RunService.task_status_for_run_result(mode, status, details=details)

    @staticmethod
    def _task_phase_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskPhase:
        return RunService.task_phase_for_run_result(mode, status, details=details)
