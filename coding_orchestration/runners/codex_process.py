from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .base import RunResult
from .codex_report import normalize_report_status
from ..models import AgentRunStatus, ArtifactSet, RunMode


class CodexProcessCallbacks(Protocol):
    def collect_artifacts(self, run_dir: Path) -> ArtifactSet:
        ...

    def build_fallback_report(self, **kwargs: Any) -> dict[str, Any]:
        ...

    def load_or_build_report(self, run_dir: Path, mode: RunMode) -> dict[str, Any]:
        ...


@dataclass
class CodexProcessRunner:
    callbacks: CodexProcessCallbacks
    processes: dict[str, subprocess.Popen] = field(default_factory=dict)

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
                self.processes[run_id] = proc
                try:
                    exit_code = proc.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    self.cancel(run_id)
                    exit_code = proc.wait(timeout=5)
                    self.update_run_manifest_timing(
                        run_dir,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                    )
                    report = self.callbacks.build_fallback_report(run_dir=run_dir, mode=mode, status="timeout")
                    return RunResult(report["status"], exit_code, self.callbacks.collect_artifacts(run_dir), report)
                finally:
                    self.processes.pop(run_id, None)
        except Exception as exc:
            self.update_run_manifest_timing(
                run_dir,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
            stderr_path.write_text(str(exc), encoding="utf-8")
            report = self.callbacks.build_fallback_report(
                run_dir=run_dir,
                mode=mode,
                status="runner_failed",
                limitation_reason="process_start_failed",
                limitation_impact="Codex runner did not start, so no implementation or verification ran.",
                limitation_recovery_action="Verify the Codex CLI command/path and rerun this task.",
                limitation_fallback_evidence=str(stderr_path),
            )
            return RunResult(report["status"], None, self.callbacks.collect_artifacts(run_dir), report)

        self.update_run_manifest_timing(
            run_dir,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )
        report = self.callbacks.load_or_build_report(run_dir=run_dir, mode=mode)
        status = normalize_report_status(report.get("status", AgentRunStatus.FAILED.value), mode)
        return RunResult(status, exit_code, self.callbacks.collect_artifacts(run_dir), report)

    def cancel(self, run_id: str) -> bool:
        proc = self.processes.get(run_id)
        if proc is None or proc.poll() is not None:
            return False
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False

    @staticmethod
    def update_run_manifest_timing(
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
