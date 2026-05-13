from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Any

from .base import CodingAgentRunner, RunResult
from ..models import AgentRunStatus, ArtifactSet, RunMode, RunnerCapabilities


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
            str(run_dir / "report.json"),
            "--sandbox",
            sandbox,
            "-c",
            'approval_policy="never"',
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
        raw_report = ""
        if report_path.exists():
            try:
                raw_report = report_path.read_text(encoding="utf-8")
                report = json.loads(raw_report)
                if self._is_valid_report(report):
                    self.ensure_summary(run_dir, report)
                    return report
            except json.JSONDecodeError:
                pass
        recovered_summary = self.recover_summary_markdown(run_dir=run_dir, raw_report=raw_report)
        return self.build_fallback_report(
            run_dir=run_dir,
            mode=mode,
            recovered_summary=recovered_summary,
        )

    def ensure_summary(self, run_dir: Path, report: dict[str, Any]) -> None:
        summary = str(report.get("summary_markdown") or "").strip()
        if not summary:
            next_actions = "\n".join(f"- {item}" for item in report.get("next_actions") or [])
            risks = "\n".join(f"- {item}" for item in report.get("risks") or [])
            parts = [
                f"Status: {report.get('status', 'unknown')}",
                "",
                "Next actions:",
                next_actions or "- none",
            ]
            if risks:
                parts.extend(["", "Risks:", risks])
            summary = "\n".join(parts)
        (run_dir / "summary.md").write_text(summary, encoding="utf-8")

    def build_fallback_report(
        self,
        run_dir: Path,
        mode: RunMode,
        status: AgentRunStatus = AgentRunStatus.COMPLETED_UNSTRUCTURED,
        recovered_summary: str = "",
    ) -> dict[str, Any]:
        risks = ["Structured report was not produced or failed schema validation."]
        next_actions = ["Review stdout/stderr and decide whether to rerun or continue manually."]
        if recovered_summary:
            (run_dir / "summary.md").write_text(recovered_summary, encoding="utf-8")
            risks.append("已从非结构化输出中恢复可读计划；仍需人工确认完整度和正确性。")
            next_actions = ["请人工确认计划完整度和正确性；确认后再进入 implementation。"]
        report = {
            "runner": self.name,
            "status": status.value,
            "mode": mode.value,
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": risks,
            "human_required": True,
            "next_actions": next_actions,
            "raw_stdout_ref": str(run_dir / "stdout.log"),
            "raw_stderr_ref": str(run_dir / "stderr.log"),
            "summary_ref": str(run_dir / "summary.md"),
        }
        if recovered_summary:
            report["summary_markdown"] = recovered_summary
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def recover_summary_markdown(self, *, run_dir: Path, raw_report: str = "") -> str:
        candidates = [
            self._summary_from_json_or_markdown(raw_report),
            self._summary_from_stdout_jsonl(run_dir / "stdout.log"),
            self._summary_from_json_or_markdown(self._read_text(run_dir / "stdout.log")),
        ]
        for candidate in candidates:
            summary = self._clean_summary(candidate)
            if summary:
                return summary
        return ""

    def _summary_from_json_or_markdown(self, text: str) -> str:
        value = text.strip()
        if not value:
            return ""
        parsed = self._try_parse_json(value)
        if isinstance(parsed, dict):
            summary = parsed.get("summary_markdown")
            if isinstance(summary, str) and summary.strip():
                return summary
        for block in re.findall(r"```(?:json|markdown|md)?\s*(.*?)```", value, flags=re.S | re.I):
            parsed_block = self._try_parse_json(block.strip())
            if isinstance(parsed_block, dict):
                summary = parsed_block.get("summary_markdown")
                if isinstance(summary, str) and summary.strip():
                    return summary
            if self._looks_like_plan(block):
                return block
        if self._looks_like_plan(value):
            return value
        return ""

    def _summary_from_stdout_jsonl(self, path: Path) -> str:
        if not path.exists():
            return ""
        messages: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = self._try_parse_json(line)
            if not isinstance(parsed, dict):
                continue
            text = self._event_text(parsed)
            if text:
                messages.append(text)
        for message in reversed(messages):
            summary = self._summary_from_json_or_markdown(message)
            if summary:
                return summary
            if self._looks_like_plan(message):
                return message
        return ""

    def _event_text(self, event: dict[str, Any]) -> str:
        for key in ("message", "text", "content", "delta", "item"):
            value = event.get(key)
            text = self._text_from_value(value)
            if text:
                return text
        return ""

    def _text_from_value(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = [self._text_from_value(item) for item in value]
            return "\n".join(part for part in parts if part)
        if isinstance(value, dict):
            for key in ("text", "content", "message"):
                text = self._text_from_value(value.get(key))
                if text:
                    return text
        return ""

    @staticmethod
    def _try_parse_json(text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _read_text(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _looks_like_plan(text: str) -> bool:
        value = text.strip()
        if len(value) < 12:
            return False
        markers = ("计划", "步骤", "实现", "测试", "风险", "Plan", "Implementation", "Tests", "Risks")
        return any(marker in value for marker in markers)

    @staticmethod
    def _clean_summary(text: str) -> str:
        value = text.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:markdown|md)?\s*", "", value, flags=re.I)
            value = re.sub(r"\s*```$", "", value)
        return value.strip()

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
