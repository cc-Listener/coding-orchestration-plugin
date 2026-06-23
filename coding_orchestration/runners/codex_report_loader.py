from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..models import RunMode
from ..reports.report_admission import admit_report
from ..reports.report_contract import validate_codex_semantic_report
from .codex_report import runner_failure_from_stdout


class CodexReportCallbacks(Protocol):
    def build_report_incomplete_report(self, run_dir: Path, mode: RunMode, missing: list[str]) -> dict[str, Any]:
        ...

    def ensure_report_contract(self, run_dir: Path, mode: RunMode, report: dict[str, Any]) -> dict[str, Any]:
        ...

    def build_report_admission_rejected_report(
        self,
        run_dir: Path,
        mode: RunMode,
        reason: str,
        errors: list[str],
    ) -> dict[str, Any]:
        ...

    def ensure_summary(self, run_dir: Path, report: dict[str, Any]) -> None:
        ...

    def build_fallback_report(self, **kwargs: Any) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class CodexReportLoader:
    callbacks: CodexReportCallbacks

    def load_or_build(self, run_dir: Path, mode: RunMode) -> dict[str, Any]:
        report_path = run_dir / "report.json"
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                if report_has_required_fields(report):
                    completeness = validate_codex_semantic_report(report, mode)
                    if not completeness.ok:
                        return self.callbacks.build_report_incomplete_report(run_dir, mode, completeness.missing)
                    report = self.callbacks.ensure_report_contract(run_dir, mode, report)
                    admission = admit_report(report, mode)
                    if not admission.accepted:
                        return self.callbacks.build_report_admission_rejected_report(
                            run_dir,
                            mode,
                            admission.reason,
                            admission.errors,
                        )
                    self.callbacks.ensure_summary(run_dir, report)
                    return report
            except json.JSONDecodeError:
                pass
        runner_failure = runner_failure_from_stdout(run_dir / "stdout.log")
        if runner_failure:
            return self.callbacks.build_fallback_report(
                run_dir=run_dir,
                mode=mode,
                status="runner_failed",
                limitation_reason=runner_failure["reason"],
                limitation_impact=runner_failure["impact"],
                limitation_recovery_action=runner_failure["recovery_action"],
                limitation_fallback_evidence=runner_failure["fallback_evidence"],
            )
        return self.callbacks.build_fallback_report(
            run_dir=run_dir,
            mode=mode,
            status="runner_failed",
            limitation_reason="structured_report_missing",
            limitation_impact="Codex did not produce a valid structured report. Hermes will not infer semantic completion from stdout/stderr.",
            limitation_recovery_action="Resume the same Codex session and ask it to write the complete structured report.",
            limitation_fallback_evidence=f"{run_dir / 'stdout.log'}; {run_dir / 'stderr.log'}",
        )


def report_has_required_fields(report: Any) -> bool:
    if not isinstance(report, dict):
        return False
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
