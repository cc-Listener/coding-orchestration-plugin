from __future__ import annotations

import json
import os
import re
import signal
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import CodingAgentRunner, RunResult
from ..models import (
    AgentRunStatus,
    ArtifactSet,
    RunMode,
    RunnerCapabilities,
    agent_run_status_details,
    normalize_agent_run_status,
)
from ..report_contract import validate_codex_semantic_report
from ..run_log_compactor import compact_run_logs


REPORT_CONTRACT_FIELDS = (
    "runner",
    "status",
    "raw_status",
    "status_detail",
    "failure_type",
    "known_gaps",
    "structured",
    "mode",
    "summary_markdown",
    "modified_files",
    "test_commands",
    "test_results",
    "risks",
    "verification_limitations",
    "human_required",
    "next_actions",
    "qa_artifacts",
    "tested_commit",
    "user_facing_summary",
    "technical_summary",
    "implementation_landed",
    "commit_sha",
    "changed_files_summary",
    "branch_slug_candidate",
    "execution_policy_decision",
    "merge_readiness",
)


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
        dangerous_bypass = self._manifest_dangerous_bypass(run_dir)
        if session_id:
            return self._build_resume_command(
                run_dir=run_dir,
                mode=mode,
                session_id=session_id,
                dangerous_bypass=dangerous_bypass,
            )
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} or dangerous_bypass:
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

    def _build_resume_command(
        self,
        *,
        run_dir: Path,
        mode: RunMode,
        session_id: str,
        dangerous_bypass: bool = False,
    ) -> list[str]:
        command = [
            self.command,
            "exec",
            "resume",
            "--json",
        ]
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} or dangerous_bypass:
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
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        started_at = datetime.now(timezone.utc)
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
                    self._update_run_manifest_timing(
                        run_dir,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                    )
                    report = self.build_fallback_report(run_dir, mode, status="timeout")
                    return RunResult(report["status"], exit_code, self.collect_artifacts(run_dir), report)
                finally:
                    self._processes.pop(run_id, None)
        except Exception as exc:
            self._update_run_manifest_timing(
                run_dir,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
            stderr_path.write_text(str(exc), encoding="utf-8")
            report = self.build_fallback_report(
                run_dir,
                mode,
                status="runner_failed",
                limitation_reason="process_start_failed",
                limitation_impact="Codex runner did not start, so no implementation or verification ran.",
                limitation_recovery_action="Verify the Codex CLI command/path and rerun this task.",
                limitation_fallback_evidence=str(stderr_path),
            )
            return RunResult(report["status"], None, self.collect_artifacts(run_dir), report)

        self._update_run_manifest_timing(
            run_dir,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )
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

    @staticmethod
    def _update_run_manifest_timing(
        run_dir: Path,
        *,
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        manifest_path = run_dir / "run-manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(loaded, dict):
                    manifest = loaded
            except Exception:
                manifest = {}
        duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
        manifest.update(
            {
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
            }
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

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
            operator_log=run_dir / "run-log.md",
            execution_policy=run_dir / "execution-policy.json",
        )

    def load_or_build_report(self, run_dir: Path, mode: RunMode) -> dict[str, Any]:
        report_path = run_dir / "report.json"
        raw_report = ""
        if report_path.exists():
            try:
                raw_report = report_path.read_text(encoding="utf-8")
                report = json.loads(raw_report)
                if self._is_valid_report(report):
                    completeness = validate_codex_semantic_report(report, mode)
                    if not completeness.ok:
                        return self.build_report_incomplete_report(run_dir, mode, completeness.missing)
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
                status="runner_failed",
                limitation_reason=runner_failure["reason"],
                limitation_impact=runner_failure["impact"],
                limitation_recovery_action=runner_failure["recovery_action"],
                limitation_fallback_evidence=runner_failure["fallback_evidence"],
            )
        return self.build_fallback_report(
            run_dir=run_dir,
            mode=mode,
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
        status: Any = "completed_unstructured",
        recovered_summary: str = "",
        limitation_reason: str = "",
        limitation_impact: str = "",
        limitation_recovery_action: str = "",
        limitation_fallback_evidence: str = "",
    ) -> dict[str, Any]:
        details = agent_run_status_details(status, mode)
        if details.get("failure_type") == "timeout" or details.get("raw_status") == "timeout":
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
            default_impact = "Hermes cannot fully trust this run result because Python semantic fallback from stdout/stderr is disabled."
            default_recovery_action = "Rerun or resume Codex so it writes a complete structured report; Hermes will not infer semantic completion from stdout/stderr."
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
            **details,
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
            **self._semantic_report_fields({}),
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._attach_operator_log_refs(run_dir, report)

    def build_report_incomplete_report(
        self,
        run_dir: Path,
        mode: RunMode,
        missing: list[str],
    ) -> dict[str, Any]:
        missing_text = ", ".join(missing)
        limitation = self._verification_limitation(
            reason="codex_report_incomplete",
            impact="Codex 输出的结构化 report 缺少 Hermes 必须消费的语义字段。",
            recovery_action="续接 Codex，让它补齐完整结构化 report。",
            fallback_evidence=str(run_dir / "report.json"),
        )
        report = {
            "runner": self.name,
            **agent_run_status_details(AgentRunStatus.BLOCKED.value, mode),
            "failure_type": "report_incomplete",
            "mode": mode.value,
            "summary_markdown": "Codex 输出缺少必要结构化字段，Hermes 不会用 Python 猜测结果。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": ["Codex report incomplete; Python semantic fallback is disabled."],
            "verification_limitations": [limitation],
            "human_required": True,
            "next_actions": ["续接 Codex，让它补齐完整结构化 report。"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "user_facing_summary": "Codex 结果不完整，需要续接补齐。",
            "technical_summary": f"缺少字段：{missing_text}",
            "implementation_landed": False,
            "commit_sha": "",
            "changed_files_summary": [],
            "branch_slug_candidate": "",
            "execution_policy_decision": {},
            "merge_readiness": {},
        }
        report = self._report_contract_fields(report)
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._attach_operator_log_refs(run_dir, report)

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
            candidate.get("raw_status")
            or candidate.get("status_detail")
            or candidate.get("status")
            or "completed_unstructured",
            mode,
        )
        details = self._report_status_details(candidate, mode)
        status = details["status"]
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
            **details,
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
                    },
                )
            ),
            "next_actions": next_actions,
            "qa_artifacts": candidate.get("qa_artifacts")
            if isinstance(candidate.get("qa_artifacts"), dict)
            else {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": str(candidate.get("tested_commit") or ""),
            **self._semantic_report_fields(candidate),
        }

    @staticmethod
    def _semantic_report_fields(report: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_facing_summary": str(report.get("user_facing_summary") or ""),
            "technical_summary": str(report.get("technical_summary") or ""),
            "implementation_landed": report.get("implementation_landed")
            if isinstance(report.get("implementation_landed"), bool)
            else False,
            "commit_sha": str(report.get("commit_sha") or ""),
            "changed_files_summary": report.get("changed_files_summary")
            if isinstance(report.get("changed_files_summary"), list)
            else [],
            "branch_slug_candidate": str(report.get("branch_slug_candidate") or ""),
            "execution_policy_decision": report.get("execution_policy_decision")
            if isinstance(report.get("execution_policy_decision"), dict)
            else {},
            "merge_readiness": report.get("merge_readiness")
            if isinstance(report.get("merge_readiness"), dict)
            else {},
        }

    @staticmethod
    def _default_next_actions_for_status(status: str, mode: RunMode, run_dir: Path) -> list[str]:
        task_id = run_dir.parent.name
        details = agent_run_status_details(status, mode)
        canonical = str(details.get("status") or "")
        if mode == RunMode.PLAN_ONLY:
            return [f"人工确认计划后发送 /coding implement {task_id}。"]
        if mode == RunMode.IMPLEMENTATION:
            if details.get("known_gaps") or details.get("status_detail") == "ready_for_merge_test_with_known_gaps":
                return [f"开发完成但存在已知验证缺口；确认风险或补验证后发送 /coding merge-test {task_id}。"]
            if canonical == AgentRunStatus.SUCCEEDED.value:
                return [f"开发和验证完成，确认后发送 /coding merge-test {task_id}。"]
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
        report.update(self._report_status_details(report, mode))
        report.setdefault("summary_markdown", "")
        report.setdefault("verification_limitations", [])
        report.setdefault("qa_artifacts", {"report": "", "baseline": "", "screenshots_dir": ""})
        report.setdefault("tested_commit", "")
        report.update(self._semantic_report_fields(report))
        if self._report_requires_limitation(report) and not report["verification_limitations"]:
            report["verification_limitations"] = [
                self._verification_limitation(
                    reason="blocked_or_partial_without_details",
                    impact="The runner reported a blocked or partial result without structured recovery details.",
                    recovery_action="Review risks, stdout/stderr, and rerun with explicit recovery instructions.",
                    fallback_evidence=f"{run_dir / 'stdout.log'}; {run_dir / 'stderr.log'}",
                )
            ]
        report = self._report_contract_fields(report)
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._attach_operator_log_refs(run_dir, report)

    def _attach_operator_log_refs(self, run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
        report = dict(report)
        try:
            compact_run_logs(run_dir)
        except Exception:
            return report
        return report

    @staticmethod
    def _report_contract_fields(report: dict[str, Any]) -> dict[str, Any]:
        return {key: report[key] for key in REPORT_CONTRACT_FIELDS if key in report}

    @staticmethod
    def _normalize_report_status(status: Any, mode: RunMode) -> str:
        return normalize_agent_run_status(status, mode)

    @staticmethod
    def _report_status_details(report: dict[str, Any], mode: RunMode) -> dict[str, Any]:
        source_status = (
            report.get("raw_status")
            or report.get("status_detail")
            or report.get("status")
            or "completed_unstructured"
        )
        details = agent_run_status_details(source_status, mode)
        status_detail = str(report.get("status_detail") or "").strip()
        failure_type = str(report.get("failure_type") or "").strip()
        if status_detail:
            details["status_detail"] = status_detail
        if failure_type:
            details["failure_type"] = failure_type
            details["status"] = AgentRunStatus.FAILED.value
        if "known_gaps" in report:
            details["known_gaps"] = bool(report.get("known_gaps"))
        if "structured" in report:
            details["structured"] = bool(report.get("structured"))
        if details["known_gaps"] and not details["status_detail"]:
            details["status_detail"] = "ready_for_merge_test_with_known_gaps"
        if details["structured"] is False and not details["status_detail"]:
            details["status_detail"] = "completed_unstructured"
        return details

    @staticmethod
    def _status_requires_limitation(status: Any) -> bool:
        details = agent_run_status_details(status)
        return CodexCliRunner._detail_requires_limitation(details)

    @staticmethod
    def _report_requires_limitation(report: dict[str, Any]) -> bool:
        return CodexCliRunner._detail_requires_limitation(
            {
                "status": str(report.get("status") or ""),
                "status_detail": str(report.get("status_detail") or ""),
                "failure_type": str(report.get("failure_type") or ""),
                "known_gaps": bool(report.get("known_gaps")),
                "structured": bool(report.get("structured", True)),
            }
        )

    @staticmethod
    def _detail_requires_limitation(details: dict[str, Any]) -> bool:
        status = str(details.get("status") or "")
        return bool(
            status in {AgentRunStatus.BLOCKED.value, AgentRunStatus.FAILED.value}
            or details.get("known_gaps")
            or details.get("failure_type")
            or details.get("status_detail") in {"completed_unstructured", "ready_for_merge_test_with_known_gaps"}
            or details.get("structured") is False
        )

    @staticmethod
    def _fallback_limitation_reason(status: Any) -> str:
        details = agent_run_status_details(status)
        failure_type = str(details.get("failure_type") or "")
        if failure_type == "timeout" or details.get("raw_status") == "timeout":
            return "runner_timeout"
        if failure_type == "runner_failed" or details.get("raw_status") == "runner_failed":
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

    @staticmethod
    def _manifest_dangerous_bypass(run_dir: Path) -> bool:
        manifest_path = run_dir / "run-manifest.json"
        if not manifest_path.exists():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return bool(manifest.get("dangerous_bypass"))
