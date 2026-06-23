from __future__ import annotations

from pathlib import Path
from typing import Any

from . import run_orchestration_service, run_report_artifact_service, run_stderr_artifact_service, run_summary_artifact_service
from .models import RunMode
from .runners.base import RunResult
from .services import RunService, TaskService
from .symphony_compat.workflow_loader import WorkflowSpec


class OrchestratorRuntimeFacadeMixin:
    @staticmethod
    def _extract_flag(text: str, flag: str) -> str | None:
        return TaskService.extract_flag(text, flag)

    @staticmethod
    def _strip_flags(text: str) -> str:
        return TaskService.strip_flags(text)

    def _project_name_for_path(self, project_path: str) -> str | None:
        for project in self.resolver.registry.projects:
            if Path(project.path).expanduser().resolve() == Path(project_path).expanduser().resolve():
                return project.name
        return None

    def _workflow_for_project(self, project_path: Path) -> WorkflowSpec:
        loaded = self.workflow_loader.load(project_path)
        project = None
        for item in self.resolver.registry.projects:
            if Path(item.path).expanduser().resolve() == project_path:
                project = item
                break
        if project is None:
            return loaded
        return WorkflowSpec(
            project_path=loaded.project_path,
            allowed_paths=loaded.allowed_paths or list(project.allowed_paths),
            forbidden_paths=loaded.forbidden_paths or list(project.forbidden_paths),
            default_test_commands=loaded.default_test_commands or list(project.default_test_commands),
            plan_required=loaded.plan_required,
            implementation_allowed=loaded.implementation_allowed,
            merge_policy=loaded.merge_policy,
            publish_policy=loaded.publish_policy,
            recommended_runner=loaded.recommended_runner or project.default_runner,
            notes=loaded.notes,
        )

    @staticmethod
    def _plan_report_session_fields(report: dict[str, Any]) -> dict[str, Any]:
        return run_orchestration_service.build_plan_report_session_fields(report)

    @staticmethod
    def _latest_execution_policy_decision(task: dict[str, Any]) -> dict[str, Any]:
        return run_orchestration_service.latest_execution_policy_decision(task)

    def _timeout_seconds_for_mode(
        self,
        mode: RunMode,
        override: int | None = None,
        execution_policy: dict[str, Any] | None = None,
    ) -> int:
        return self.run_service.timeout_seconds_for_mode(mode, override, execution_policy=execution_policy)

    @staticmethod
    def _policy_timeout_seconds(execution_policy: dict[str, Any] | None) -> int:
        return RunService.policy_timeout_seconds(execution_policy)

    @staticmethod
    def _policy_uses_targeted_verification(execution_policy: dict[str, Any] | None) -> bool:
        return RunService.policy_uses_targeted_verification(execution_policy)

    def _runner_failed_result(self, *, runner_name: str, run_dir: Path, mode: RunMode, error: Exception) -> RunResult:
        artifacts = self._artifact_set_for_run_dir(run_dir)
        artifacts.stdout.touch(exist_ok=True)
        failure = run_orchestration_service.build_runner_failed_report_payload(
            runner_name=runner_name,
            mode=mode,
            error=error,
            stdout_path=artifacts.stdout,
            stderr_path=artifacts.stderr,
            summary_path=artifacts.summary,
        )
        run_stderr_artifact_service.write_run_stderr_artifact(stderr_path=artifacts.stderr, stderr=failure.stderr)
        run_summary_artifact_service.write_run_summary_artifact(summary_path=artifacts.summary, summary=failure.summary)
        run_report_artifact_service.write_run_report_artifact(report_path=artifacts.report, report=failure.report)
        return RunResult(
            status=failure.status,
            exit_code=None,
            artifacts=artifacts,
            report=failure.report,
        )

    def _checkpoint_failed_result(
        self,
        *,
        runner_name: str,
        run_dir: Path,
        mode: RunMode,
        checkpoint: dict[str, Any],
    ) -> RunResult:
        artifacts = self._artifact_set_for_run_dir(run_dir)
        artifacts.stdout.touch(exist_ok=True)
        failure = run_orchestration_service.build_checkpoint_failed_report_payload(
            runner_name=runner_name,
            mode=mode,
            checkpoint=checkpoint,
            stderr_path=artifacts.stderr,
        )
        run_stderr_artifact_service.write_run_stderr_artifact(stderr_path=artifacts.stderr, stderr=failure.stderr)
        run_summary_artifact_service.write_run_summary_artifact(summary_path=artifacts.summary, summary=failure.summary)
        run_report_artifact_service.write_run_report_artifact(report_path=artifacts.report, report=failure.report)
        return RunResult(
            status=failure.status,
            exit_code=None,
            artifacts=artifacts,
            report=failure.report,
        )
