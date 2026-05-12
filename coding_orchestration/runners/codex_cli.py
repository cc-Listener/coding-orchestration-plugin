from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, RunnerCapabilities
from .base import CodingAgentRunner, RunResult


class CodexCliRunner(CodingAgentRunner):
    name = "codex_cli"

    def __init__(self, command: str = "codex"):
        self.command = command
        self._processes: dict[str, subprocess.Popen] = {}

    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(
            supports_plan_only=True,
            supports_implementation=True,
            supports_streaming_events=True,
            supports_cancel=True,
            supports_resume=False,
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
        cwd = workspace_path if mode == RunMode.IMPLEMENTATION else project_path
        sandbox = "workspace-write" if mode == RunMode.IMPLEMENTATION else "read-only"
        return [
            self.command,
            "exec",
            "--json",
            "--output-schema",
            str(run_dir / "report.schema.json"),
            "--output-last-message",
            str(run_dir / "summary.md"),
            "--sandbox",
            sandbox,
            "--ask-for-approval",
            "never",
            "-C",
            str(cwd),
            "-",
        ]

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
        return self.run_subprocess(
            run_id=run_id,
            command=command,
            run_dir=run_dir,
            stdin_path=run_dir / "input-prompt.md",
            timeout_seconds=timeout_seconds,
            mode=mode,
        )

    def run_subprocess(
        self,
        *,
        run_id: str,
        command: list[str],
        run_dir: Path,
        stdin_path: Path,
        timeout_seconds: int,
        mode: RunMode = RunMode.PLAN_ONLY,
    ) -> RunResult:
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        with stdin_path.open("rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            proc = subprocess.Popen(
                command,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            self._processes[run_id] = proc
            try:
                exit_code = proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self.cancel(run_id)
                exit_code = proc.wait(timeout=5)
                report = self.build_fallback_report(run_dir, mode, status=AgentRunStatus.TIMEOUT)
                return RunResult(AgentRunStatus.TIMEOUT.value, exit_code, self.collect_artifacts(run_dir), report)
            finally:
                self._processes.pop(run_id, None)

        report = self.load_or_build_report(run_dir=run_dir, mode=mode)
        return RunResult(str(report.get("status", AgentRunStatus.FAILED.value)), exit_code, self.collect_artifacts(run_dir), report)

    def cancel(self, run_id: str) -> bool:
        proc = self._processes.get(run_id)
        if proc is None or proc.poll() is not None:
            return False
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False

    def collect_artifacts(self, run_dir: Path) -> ArtifactSet:
        return ArtifactSet(
            run_dir=run_dir,
            input_prompt=run_dir / "input-prompt.md",
            manifest=run_dir / "run-manifest.json",
            stdout=run_dir / "stdout.log",
            stderr=run_dir / "stderr.log",
            events=run_dir / "events.jsonl",
            report=run_dir / "report.json",
            summary=run_dir / "summary.md",
            diff=run_dir / "diff.patch",
        )

    def load_or_build_report(self, run_dir: Path, mode: RunMode) -> dict[str, Any]:
        report_path = run_dir / "report.json"
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                if self._is_valid_report(report):
                    return report
            except json.JSONDecodeError:
                pass
        return self.build_fallback_report(run_dir=run_dir, mode=mode)

    def build_fallback_report(
        self,
        run_dir: Path,
        mode: RunMode,
        status: AgentRunStatus = AgentRunStatus.COMPLETED_UNSTRUCTURED,
    ) -> dict[str, Any]:
        report = {
            "runner": self.name,
            "status": status.value,
            "mode": mode.value,
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": ["Structured report was not produced or failed schema validation."],
            "human_required": True,
            "next_actions": ["Review stdout/stderr and decide whether to rerun or continue manually."],
            "raw_stdout_ref": str(run_dir / "stdout.log"),
            "raw_stderr_ref": str(run_dir / "stderr.log"),
            "summary_ref": str(run_dir / "summary.md"),
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    @staticmethod
    def _is_valid_report(report: dict[str, Any]) -> bool:
        required = {
            "runner",
            "status",
            "mode",
            "modified_files",
            "test_commands",
            "test_results",
            "risks",
            "human_required",
            "next_actions",
        }
        return required.issubset(report.keys())
