from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import CodingAgentRunner, RunResult
from .codex_artifacts import collect_codex_artifacts
from .codex_command import (
    CodexCommandBuilder,
    build_resume_command,
    manifest_dangerous_bypass,
    resume_session_id,
)
from .codex_process import CodexProcessRunner
from .codex_report import (
    fallback_limitation_reason,
    normalize_report_status,
    report_contract_fields,
    report_requires_limitation,
    report_status_details,
    run_details_require_limitation,
    runner_failure_from_stdout,
    semantic_report_fields,
    status_requires_limitation,
    thread_id_from_stdout as report_thread_id_from_stdout,
    try_parse_json,
    verification_limitation,
)
from .codex_report_loader import CodexReportLoader, report_has_required_fields
from .codex_report_writer import CodexReportWriter
from ..models import (
    AgentRunStatus,
    ArtifactSet,
    RunMode,
    RunnerCapabilities,
    agent_run_status_details,
)


class CodexCliRunner(CodingAgentRunner):
    name = "codex_cli"

    def __init__(self, command: str = "codex", hermes_runtime: Any | None = None):
        self.command = command
        self.hermes_runtime = hermes_runtime
        self.process_runner = CodexProcessRunner(self)
        self.report_writer = CodexReportWriter(runner_name=self.name)

    def set_hermes_runtime(self, hermes_runtime: Any) -> None:
        self.hermes_runtime = hermes_runtime

    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(
            supports_plan_only=True,
            supports_implementation=True,
            supports_streaming_events=True,
            supports_cancel=True,
            supports_resume=True,
            supports_app_server=False,
            supports_structured_output=True,
            output_format="json_events",
            sandbox_level="cli_flags",
        )

    def build_command(
        self,
        run_dir: Path,
        project_path: Path,
        workspace_path: Path | None,
        mode: RunMode,
    ) -> list[str]:
        return CodexCommandBuilder(command=self.command).build(
            run_dir=run_dir,
            project_path=project_path,
            workspace_path=workspace_path,
            mode=mode,
        )

    def _build_resume_command(
        self,
        *,
        run_dir: Path,
        mode: RunMode,
        session_id: str,
        dangerous_bypass: bool = False,
    ) -> list[str]:
        return build_resume_command(
            command=self.command,
            run_dir=run_dir,
            mode=mode,
            session_id=session_id,
            dangerous_bypass=dangerous_bypass,
        )

    def run(
        self,
        *,
        run_id: str,
        run_dir: Path,
        project_path: Path,
        workspace_path: Path | None,
        mode: RunMode,
        timeout_seconds: int,
    ) -> RunResult:
        command = self.build_command(
            run_dir=run_dir,
            project_path=project_path,
            workspace_path=workspace_path,
            mode=mode,
        )
        subprocess_cwd = self.subprocess_cwd(
            project_path=project_path,
            workspace_path=workspace_path,
            mode=mode,
        )
        if self.hermes_runtime is not None and self.hermes_runtime.available():
            return self.run_hermes_runtime(
                run_id=run_id,
                command=command,
                run_dir=run_dir,
                stdin_path=run_dir / "input-prompt.md",
                mode=mode,
                cwd=subprocess_cwd,
            )
        return self.run_subprocess(
            run_id=run_id,
            command=command,
            run_dir=run_dir,
            stdin_path=run_dir / "input-prompt.md",
            timeout_seconds=timeout_seconds,
            mode=mode,
            cwd=subprocess_cwd,
        )

    def run_hermes_runtime(
        self,
        *,
        run_id: str,
        command: list[str],
        run_dir: Path,
        stdin_path: Path,
        mode: RunMode,
        cwd: Path,
    ) -> RunResult:
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        runtime_start_path = run_dir / "runtime-start.json"
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        result = self.hermes_runtime.start_command(
            command=shlex.join(command),
            cwd=str(cwd),
            stdin_path=str(stdin_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            watch_patterns=[
                "ready_for_merge_test",
                "ready_for_merge_test_with_known_gaps",
                "runner_failed",
                "timeout",
                AgentRunStatus.BLOCKED.value,
                AgentRunStatus.FAILED.value,
                AgentRunStatus.SUCCEEDED.value,
                "success",
            ],
        )
        runtime_start_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result.get("ok"):
            report = self.build_fallback_report(
                run_dir,
                mode,
                status="runner_failed",
                limitation_reason=str(result.get("reason") or "hermes_runtime_start_failed"),
                limitation_impact="Hermes terminal/process runtime did not start the Codex command.",
                limitation_recovery_action="Verify Hermes terminal/process tools are enabled, then retry the run.",
                limitation_fallback_evidence=str(runtime_start_path),
            )
            return RunResult(report["status"], None, self.collect_artifacts(run_dir), report)
        queued_details = agent_run_status_details("queued", mode)
        report = {
            "runner": self.name,
            **queued_details,
            "mode": mode.value,
            "summary_markdown": "Hermes runtime 已启动后台 Codex 任务。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["Use Hermes process/terminal notifications to collect completion artifacts."],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            **self._semantic_report_fields({}),
            "raw_stdout_ref": str(run_dir / "stdout.log"),
            "raw_stderr_ref": str(run_dir / "stderr.log"),
            "summary_ref": str(run_dir / "summary.md"),
            "runtime_start_ref": str(runtime_start_path),
            "runtime": result.get("raw"),
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "summary.md").write_text(str(report["summary_markdown"]), encoding="utf-8")
        return RunResult(queued_details["status"], None, self.collect_artifacts(run_dir), report)

    @staticmethod
    def subprocess_cwd(*, project_path: Path, workspace_path: Path | None, mode: RunMode) -> Path:
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} and workspace_path is not None:
            return workspace_path
        return project_path

    def run_subprocess(
        self,
        *,
        run_id: str,
        command: list[str],
        run_dir: Path,
        stdin_path: Path,
        timeout_seconds: int,
        mode: RunMode = RunMode.PLAN_ONLY,
        cwd: Path | None = None,
    ) -> RunResult:
        return self.process_runner.run_subprocess(
            run_id=run_id,
            command=command,
            run_dir=run_dir,
            stdin_path=stdin_path,
            timeout_seconds=timeout_seconds,
            mode=mode,
            cwd=cwd,
        )

    def cancel(self, run_id: str) -> bool:
        return self.process_runner.cancel(run_id)

    @staticmethod
    def _update_run_manifest_timing(
        run_dir: Path,
        *,
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        CodexProcessRunner.update_run_manifest_timing(
            run_dir,
            started_at=started_at,
            completed_at=completed_at,
        )

    def collect_artifacts(self, run_dir: Path) -> ArtifactSet:
        return collect_codex_artifacts(run_dir)

    def load_or_build_report(self, run_dir: Path, mode: RunMode) -> dict[str, Any]:
        return CodexReportLoader(self).load_or_build(run_dir, mode)

    def ensure_summary(self, run_dir: Path, report: dict[str, Any]) -> None:
        self.report_writer.ensure_summary(run_dir, report)

    def build_fallback_report(
        self,
        run_dir: Path,
        mode: RunMode,
        status: Any = "runner_failed",
        recovered_summary: str = "",
        limitation_reason: str = "",
        limitation_impact: str = "",
        limitation_recovery_action: str = "",
        limitation_fallback_evidence: str = "",
    ) -> dict[str, Any]:
        return self.report_writer.build_fallback_report(
            run_dir=run_dir,
            mode=mode,
            status=status,
            recovered_summary=recovered_summary,
            limitation_reason=limitation_reason,
            limitation_impact=limitation_impact,
            limitation_recovery_action=limitation_recovery_action,
            limitation_fallback_evidence=limitation_fallback_evidence,
        )

    def build_report_incomplete_report(
        self,
        run_dir: Path,
        mode: RunMode,
        missing: list[str],
    ) -> dict[str, Any]:
        return self.report_writer.build_report_incomplete_report(run_dir, mode, missing)

    def build_report_admission_rejected_report(
        self,
        run_dir: Path,
        mode: RunMode,
        reason: str,
        errors: list[str],
    ) -> dict[str, Any]:
        return self.report_writer.build_report_admission_rejected_report(run_dir, mode, reason, errors)

    @staticmethod
    def _semantic_report_fields(report: dict[str, Any]) -> dict[str, Any]:
        return semantic_report_fields(report)

    def ensure_report_contract(self, run_dir: Path, mode: RunMode, report: dict[str, Any]) -> dict[str, Any]:
        return self.report_writer.ensure_report_contract(run_dir, mode, report)

    def _attach_operator_log_refs(self, run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
        return self.report_writer.attach_operator_log_refs(run_dir, report)

    @staticmethod
    def _report_contract_fields(report: dict[str, Any]) -> dict[str, Any]:
        return report_contract_fields(report)

    @staticmethod
    def _normalize_report_status(status: Any, mode: RunMode) -> str:
        return normalize_report_status(status, mode)

    @staticmethod
    def _report_status_details(report: dict[str, Any], mode: RunMode) -> dict[str, Any]:
        return report_status_details(report, mode)

    @staticmethod
    def _status_requires_limitation(status: Any) -> bool:
        return status_requires_limitation(status)

    @staticmethod
    def _report_requires_limitation(report: dict[str, Any]) -> bool:
        return report_requires_limitation(report)

    @staticmethod
    def _detail_requires_limitation(details: dict[str, Any]) -> bool:
        return run_details_require_limitation(details)

    @staticmethod
    def _fallback_limitation_reason(status: Any) -> str:
        return fallback_limitation_reason(status)

    @staticmethod
    def _verification_limitation(
        *,
        reason: str,
        impact: str,
        recovery_action: str,
        fallback_evidence: str,
    ) -> dict[str, str]:
        return verification_limitation(
            reason=reason,
            impact=impact,
            recovery_action=recovery_action,
            fallback_evidence=fallback_evidence,
        )

    @staticmethod
    def _try_parse_json(text: str) -> Any:
        return try_parse_json(text)

    @staticmethod
    def _runner_failure_from_stdout(path: Path) -> dict[str, str] | None:
        return runner_failure_from_stdout(path)

    @staticmethod
    def _is_valid_report(report: dict[str, Any]) -> bool:
        return report_has_required_fields(report)

    @staticmethod
    def thread_id_from_stdout(path: Path) -> str:
        return report_thread_id_from_stdout(path)

    @staticmethod
    def _resume_session_id(run_dir: Path) -> str:
        return resume_session_id(run_dir)

    @staticmethod
    def _manifest_dangerous_bypass(run_dir: Path) -> bool:
        return manifest_dangerous_bypass(run_dir)
