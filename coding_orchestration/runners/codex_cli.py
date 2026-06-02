from __future__ import annotations

import json
import os
import re
import signal
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .base import CodingAgentRunner, RunResult
from ..models import AgentRunStatus, ArtifactSet, RunMode, RunnerCapabilities, normalize_agent_run_status


class CodexCliRunner(CodingAgentRunner):
    name = "codex_cli"

    def __init__(self, command: str = "codex", hermes_runtime: Any | None = None):
        self.command = command
        self.hermes_runtime = hermes_runtime
        self._processes: dict[str, subprocess.Popen] = {}

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
        session_id = self._resume_session_id(run_dir)
        if session_id:
            return self._build_resume_command(run_dir=run_dir, mode=mode, session_id=session_id)
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}:
            cwd = workspace_path or project_path
            command = [
                self.command,
                "exec",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
            ]
            if mode != RunMode.MERGE_TEST:
                command.extend(
                    [
                        "--output-schema",
                        str(run_dir / "report.schema.json"),
                    ]
                )
            command.extend(
                [
                    "--output-last-message",
                    str(run_dir / "report.json"),
                    "-C",
                    str(cwd),
                    "-",
                ]
            )
            return command

        return [
            self.command,
            "exec",
            "--json",
            "--output-schema",
            str(run_dir / "report.schema.json"),
            "--output-last-message",
            str(run_dir / "report.json"),
            "--sandbox",
            "read-only",
            "-c",
            'approval_policy="never"',
            "-C",
            str(project_path),
            "-",
        ]

    def _build_resume_command(self, *, run_dir: Path, mode: RunMode, session_id: str) -> list[str]:
        command = [
            self.command,
            "exec",
            "resume",
            "--json",
        ]
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}:
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            command.extend(
                [
                    "-c",
                    'sandbox_mode="read-only"',
                    "-c",
                    'approval_policy="never"',
                ]
            )
        command.extend(
            [
                "--output-last-message",
                str(run_dir / "report.json"),
                session_id,
                "-",
            ]
        )
        return command

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
        result = self.hermes_runtime.start_command(
            command=shlex.join(command),
            cwd=str(cwd),
            stdin_path=str(stdin_path),
            watch_patterns=[
                AgentRunStatus.READY_FOR_MERGE_TEST.value,
                AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
                AgentRunStatus.RUNNER_FAILED.value,
                AgentRunStatus.BLOCKED.value,
                AgentRunStatus.FAILED.value,
            ],
        )
        (run_dir / "stdout.log").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        if not result.get("ok"):
            report = self.build_fallback_report(
                run_dir,
                mode,
                status=AgentRunStatus.RUNNER_FAILED,
                limitation_reason=str(result.get("reason") or "hermes_runtime_start_failed"),
                limitation_impact="Hermes terminal/process runtime did not start the Codex command.",
                limitation_recovery_action="Verify Hermes terminal/process tools are enabled, then retry the run.",
                limitation_fallback_evidence=str(run_dir / "stdout.log"),
            )
            return RunResult(AgentRunStatus.RUNNER_FAILED.value, None, self.collect_artifacts(run_dir), report)
        report = {
            "runner": self.name,
            "status": AgentRunStatus.QUEUED.value,
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
            "raw_stdout_ref": str(run_dir / "stdout.log"),
            "raw_stderr_ref": str(run_dir / "stderr.log"),
            "summary_ref": str(run_dir / "summary.md"),
            "runtime": result.get("raw"),
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "summary.md").write_text(str(report["summary_markdown"]), encoding="utf-8")
        return RunResult(AgentRunStatus.QUEUED.value, None, self.collect_artifacts(run_dir), report)

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
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        try:
            with stdin_path.open("rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                proc = subprocess.Popen(
                    command,
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    cwd=str(cwd) if cwd else None,
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
        except Exception as exc:
            stderr_path.write_text(str(exc), encoding="utf-8")
            report = self.build_fallback_report(
                run_dir,
                mode,
                status=AgentRunStatus.RUNNER_FAILED,
                limitation_reason="process_start_failed",
                limitation_impact="Codex runner did not start, so no implementation or verification ran.",
                limitation_recovery_action="Verify the Codex CLI command/path and rerun this task.",
                limitation_fallback_evidence=str(stderr_path),
            )
            return RunResult(AgentRunStatus.RUNNER_FAILED.value, None, self.collect_artifacts(run_dir), report)

        report = self.load_or_build_report(run_dir=run_dir, mode=mode)
        status = self._normalize_report_status(report.get("status", AgentRunStatus.FAILED.value), mode)
        return RunResult(status, exit_code, self.collect_artifacts(run_dir), report)

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
                    report = self.ensure_report_contract(run_dir, mode, report)
                    self.ensure_summary(run_dir, report)
                    return report
            except json.JSONDecodeError:
                pass
        runner_failure = self._runner_failure_from_stdout(run_dir / "stdout.log")
        if runner_failure:
            return self.build_fallback_report(
                run_dir=run_dir,
                mode=mode,
                status=AgentRunStatus.RUNNER_FAILED,
                limitation_reason=runner_failure["reason"],
                limitation_impact=runner_failure["impact"],
                limitation_recovery_action=runner_failure["recovery_action"],
                limitation_fallback_evidence=runner_failure["fallback_evidence"],
            )
        recovered_report = self.recover_partial_structured_report(run_dir=run_dir, raw_report=raw_report, mode=mode)
        if recovered_report:
            recovered_report = self.ensure_report_contract(run_dir, mode, recovered_report)
            self.ensure_summary(run_dir, recovered_report)
            return recovered_report
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
        limitation_reason: str = "",
        limitation_impact: str = "",
        limitation_recovery_action: str = "",
        limitation_fallback_evidence: str = "",
    ) -> dict[str, Any]:
        if status == AgentRunStatus.TIMEOUT:
            risks = ["Codex runner reached the configured timeout before producing the final structured report."]
            next_actions = [
                "Review stdout/stderr to confirm the latest implementation and verification state.",
                "If code changes are present, continue the same task or proceed with known verification gaps.",
            ]
            default_impact = "The runner may have completed useful implementation work, but Hermes cannot trust the final state without reviewing partial output."
            default_recovery_action = "Resume the same Codex session or rerun the task with a longer timeout after reviewing stdout/stderr."
        else:
            risks = ["Structured report was not produced or failed schema validation."]
            next_actions = ["Review stdout/stderr and decide whether to rerun or continue manually."]
            default_impact = "Hermes cannot fully trust this run result without human review."
            default_recovery_action = "Review stdout/stderr and rerun or continue manually."
        if recovered_summary:
            (run_dir / "summary.md").write_text(recovered_summary, encoding="utf-8")
            risks.append("已从非结构化输出中恢复可读摘要；仍需人工确认完整度和正确性。")
            next_actions = self._next_actions_for_recovered_summary(mode, run_dir)
        limitation = self._verification_limitation(
            reason=limitation_reason or self._fallback_limitation_reason(status),
            impact=limitation_impact or default_impact,
            recovery_action=limitation_recovery_action or default_recovery_action,
            fallback_evidence=limitation_fallback_evidence or f"{run_dir / 'stdout.log'}; {run_dir / 'stderr.log'}",
        )
        report = {
            "runner": self.name,
            "status": status.value,
            "mode": mode.value,
            "summary_markdown": recovered_summary,
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": risks,
            "verification_limitations": [limitation],
            "human_required": True,
            "next_actions": next_actions,
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "raw_stdout_ref": str(run_dir / "stdout.log"),
            "raw_stderr_ref": str(run_dir / "stderr.log"),
            "summary_ref": str(run_dir / "summary.md"),
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def recover_partial_structured_report(
        self,
        *,
        run_dir: Path,
        raw_report: str,
        mode: RunMode,
    ) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        parsed_raw = self._try_parse_json(raw_report.strip()) if raw_report.strip() else None
        if isinstance(parsed_raw, dict):
            candidates.append(parsed_raw)
        candidates.extend(self._report_candidates_from_stdout(run_dir / "stdout.log"))
        for candidate in candidates:
            report = self._normalize_partial_structured_report(candidate, run_dir=run_dir, mode=mode)
            if report:
                return report
        return {}

    def _report_candidates_from_stdout(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        candidates: list[dict[str, Any]] = []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            parsed = self._try_parse_json(line.strip())
            if not isinstance(parsed, dict):
                continue
            text = self._event_text(parsed)
            if not text:
                continue
            candidates.extend(self._report_candidates_from_text(text))
        return candidates

    def _report_candidates_from_text(self, text: str) -> list[dict[str, Any]]:
        value = text.strip()
        if not value:
            return []
        candidates: list[dict[str, Any]] = []
        parsed = self._try_parse_json(value)
        if isinstance(parsed, dict):
            candidates.append(parsed)
        for block in re.findall(r"```(?:json)?\s*(.*?)```", value, flags=re.S | re.I):
            parsed_block = self._try_parse_json(block.strip())
            if isinstance(parsed_block, dict):
                candidates.append(parsed_block)
        return candidates

    def _normalize_partial_structured_report(
        self,
        candidate: dict[str, Any],
        *,
        run_dir: Path,
        mode: RunMode,
    ) -> dict[str, Any]:
        if not any(
            key in candidate
            for key in (
                "status",
                "summary_markdown",
                "modified_files",
                "changed_files",
                "test_results",
                "verification_limitations",
            )
        ):
            return {}
        status = self._normalize_report_status(
            candidate.get("status") or AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
            mode,
        )
        modified_files = candidate.get("modified_files", candidate.get("changed_files", []))
        test_results = candidate.get("test_results") if isinstance(candidate.get("test_results"), list) else []
        test_commands = candidate.get("test_commands") if isinstance(candidate.get("test_commands"), list) else []
        if not test_commands:
            test_commands = [
                str(item.get("command"))
                for item in test_results
                if isinstance(item, dict) and str(item.get("command") or "").strip()
            ]
        limitations = (
            candidate.get("verification_limitations")
            if isinstance(candidate.get("verification_limitations"), list)
            else []
        )
        risks = candidate.get("risks") if isinstance(candidate.get("risks"), list) else []
        next_actions = (
            candidate.get("next_actions")
            if isinstance(candidate.get("next_actions"), list)
            else self._default_next_actions_for_status(status, mode, run_dir)
        )
        return {
            "runner": str(candidate.get("runner") or self.name),
            "status": status,
            "mode": str(candidate.get("mode") or mode.value),
            "summary_markdown": str(candidate.get("summary_markdown") or ""),
            "modified_files": modified_files if isinstance(modified_files, list) else [],
            "test_commands": test_commands,
            "test_results": test_results,
            "risks": risks,
            "verification_limitations": limitations,
            "human_required": bool(
                candidate.get(
                    "human_required",
                    self._status_requires_limitation(status)
                    or status
                    in {
                        AgentRunStatus.BLOCKED.value,
                        AgentRunStatus.FAILED.value,
                        AgentRunStatus.TIMEOUT.value,
                    },
                )
            ),
            "next_actions": next_actions,
            "qa_artifacts": candidate.get("qa_artifacts")
            if isinstance(candidate.get("qa_artifacts"), dict)
            else {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": str(candidate.get("tested_commit") or ""),
            "raw_stdout_ref": str(run_dir / "stdout.log"),
            "raw_stderr_ref": str(run_dir / "stderr.log"),
            "summary_ref": str(run_dir / "summary.md"),
        }

    @staticmethod
    def _default_next_actions_for_status(status: str, mode: RunMode, run_dir: Path) -> list[str]:
        task_id = run_dir.parent.name
        if mode == RunMode.PLAN_ONLY:
            return [f"人工确认计划后发送 /coding implement {task_id}。"]
        if mode == RunMode.IMPLEMENTATION:
            if status == AgentRunStatus.READY_FOR_MERGE_TEST.value:
                return [f"开发和验证完成，确认后发送 /coding merge-test {task_id}。"]
            if status == AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value:
                return [f"开发完成但存在已知验证缺口；确认风险或补验证后发送 /coding merge-test {task_id}。"]
            return [f"查看 stdout/stderr 和恢复动作后，继续发送 /coding implement {task_id}。"]
        if mode == RunMode.QA:
            return [f"查看 QA 结果；确认后发送 /coding merge-test {task_id}。"]
        if mode == RunMode.MERGE_TEST:
            return [f"测试环境确认后发送 /coding complete {task_id}。"]
        return ["Review stdout/stderr and decide whether to rerun or continue manually."]

    @classmethod
    def _next_actions_for_recovered_summary(cls, mode: RunMode, run_dir: Path) -> list[str]:
        task_id = run_dir.parent.name
        if mode == RunMode.PLAN_ONLY:
            return [f"请人工确认计划完整度和正确性；确认后发送 /coding implement {task_id}。"]
        if mode == RunMode.IMPLEMENTATION:
            return [f"请人工确认实现摘要和 stdout/stderr；如实现可接受，发送 /coding prepare-merge-test {task_id} 或继续 /coding implement {task_id}。"]
        if mode == RunMode.QA:
            return [f"请人工确认 QA 摘要和 stdout/stderr；如风险可接受，发送 /coding merge-test {task_id}。"]
        if mode == RunMode.MERGE_TEST:
            return [f"请人工确认 merge-test 摘要和 stdout/stderr；测试环境确认后发送 /coding complete {task_id}。"]
        return ["Review stdout/stderr and decide whether to rerun or continue manually."]

    def ensure_report_contract(self, run_dir: Path, mode: RunMode, report: dict[str, Any]) -> dict[str, Any]:
        report = dict(report)
        report.setdefault("mode", mode.value)
        report["status"] = self._normalize_report_status(
            report.get("status") or AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
            mode,
        )
        report.setdefault("summary_markdown", "")
        report.setdefault("verification_limitations", [])
        report.setdefault("qa_artifacts", {"report": "", "baseline": "", "screenshots_dir": ""})
        report.setdefault("tested_commit", "")
        if self._status_requires_limitation(str(report.get("status") or "")) and not report["verification_limitations"]:
            report["verification_limitations"] = [
                self._verification_limitation(
                    reason="blocked_or_partial_without_details",
                    impact="The runner reported a blocked or partial result without structured recovery details.",
                    recovery_action="Review risks, stdout/stderr, and rerun with explicit recovery instructions.",
                    fallback_evidence=f"{run_dir / 'stdout.log'}; {run_dir / 'stderr.log'}",
                )
            ]
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    @staticmethod
    def _normalize_report_status(status: Any, mode: RunMode) -> str:
        return normalize_agent_run_status(status, mode)

    @staticmethod
    def _status_requires_limitation(status: str) -> bool:
        return status in {
            AgentRunStatus.BLOCKED.value,
            AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
            AgentRunStatus.RUNNER_FAILED.value,
            AgentRunStatus.TIMEOUT.value,
        }

    @staticmethod
    def _fallback_limitation_reason(status: AgentRunStatus) -> str:
        if status == AgentRunStatus.TIMEOUT:
            return "runner_timeout"
        if status == AgentRunStatus.RUNNER_FAILED:
            return "runner_failed"
        return "structured_report_missing"

    @staticmethod
    def _verification_limitation(
        *,
        reason: str,
        impact: str,
        recovery_action: str,
        fallback_evidence: str,
    ) -> dict[str, str]:
        return {
            "reason": reason,
            "impact": impact,
            "recovery_action": recovery_action,
            "fallback_evidence": fallback_evidence,
        }

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
    def _runner_failure_from_stdout(path: Path) -> dict[str, str] | None:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        if "invalid_json_schema" in text or "Invalid schema for response_format" in text:
            return {
                "reason": "codex_invalid_output_schema",
                "impact": "Codex rejected Hermes' report.schema.json before running the planning turn, so no plan or verification result was produced.",
                "recovery_action": "Fix report.schema.json generation so every object property is listed in required, then rerun the same task.",
                "fallback_evidence": str(path),
            }
        return None

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
            "summary_markdown",
            "modified_files",
            "test_commands",
            "test_results",
            "risks",
            "human_required",
            "next_actions",
            "verification_limitations",
        }
        return required.issubset(report.keys())

    @staticmethod
    def thread_id_from_stdout(path: Path) -> str:
        if not path.exists():
            return ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = CodexCliRunner._try_parse_json(line.strip())
            if not isinstance(parsed, dict):
                continue
            if parsed.get("type") == "thread.started" and parsed.get("thread_id"):
                return str(parsed["thread_id"])
        return ""

    @staticmethod
    def _resume_session_id(run_dir: Path) -> str:
        manifest_path = run_dir / "run-manifest.json"
        if not manifest_path.exists():
            return ""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        return str(manifest.get("resume_session_id") or "").strip()
