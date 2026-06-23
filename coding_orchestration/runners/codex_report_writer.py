from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import AgentRunStatus, RunMode, agent_run_status_details
from ..reports.run_log_compactor import compact_run_logs
from .codex_report import (
    fallback_limitation_reason,
    report_contract_fields,
    report_requires_limitation,
    report_status_details,
    semantic_report_fields,
    verification_limitation,
)


@dataclass(frozen=True)
class CodexReportWriter:
    runner_name: str = "codex_cli"

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
        status: Any = "runner_failed",
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
            risks.append("已记录非结构化摘要，但缺少完整结构化 report，不能据此推进流程。")
        limitation = verification_limitation(
            reason=limitation_reason or fallback_limitation_reason(status),
            impact=limitation_impact or default_impact,
            recovery_action=limitation_recovery_action or default_recovery_action,
            fallback_evidence=limitation_fallback_evidence or f"{run_dir / 'stdout.log'}; {run_dir / 'stderr.log'}",
        )
        report = {
            "runner": self.runner_name,
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
            **semantic_report_fields({}),
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.attach_operator_log_refs(run_dir, report)

    def build_report_incomplete_report(
        self,
        run_dir: Path,
        mode: RunMode,
        missing: list[str],
    ) -> dict[str, Any]:
        missing_text = ", ".join(missing)
        limitation = verification_limitation(
            reason="codex_report_incomplete",
            impact="Codex 输出的结构化 report 缺少 Hermes 必须消费的语义字段。",
            recovery_action="续接 Codex，让它补齐完整结构化 report。",
            fallback_evidence=str(run_dir / "report.json"),
        )
        report = {
            "runner": self.runner_name,
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
        report = report_contract_fields(report)
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.attach_operator_log_refs(run_dir, report)

    def build_report_admission_rejected_report(
        self,
        run_dir: Path,
        mode: RunMode,
        reason: str,
        errors: list[str],
    ) -> dict[str, Any]:
        limitation = verification_limitation(
            reason=reason,
            impact="Codex 输出的结构化 report 未通过 Hermes admission gate，不能驱动状态推进或任务物化。",
            recovery_action="续接 Codex，让它修复 report 中列出的结构化问题。",
            fallback_evidence=str(run_dir / "report.json"),
        )
        report = {
            "runner": self.runner_name,
            **agent_run_status_details(AgentRunStatus.BLOCKED.value, mode),
            "failure_type": "report_admission_rejected",
            "mode": mode.value,
            "summary_markdown": "Codex report 未通过 admission gate，Hermes 已阻止流程推进。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [f"{reason}: {'; '.join(errors)}"],
            "verification_limitations": [limitation],
            "human_required": True,
            "next_actions": ["续接 Codex 修复结构化 report，或人工补充缺失信息后重跑。"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            **semantic_report_fields({}),
        }
        report = report_contract_fields(report)
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.attach_operator_log_refs(run_dir, report)

    def ensure_report_contract(self, run_dir: Path, mode: RunMode, report: dict[str, Any]) -> dict[str, Any]:
        report = dict(report)
        report.setdefault("mode", mode.value)
        report.update(report_status_details(report, mode))
        report.setdefault("summary_markdown", "")
        report.setdefault("verification_limitations", [])
        report.setdefault("qa_artifacts", {"report": "", "baseline": "", "screenshots_dir": ""})
        report.setdefault("tested_commit", "")
        report.update(semantic_report_fields(report))
        if report_requires_limitation(report) and not report["verification_limitations"]:
            report["verification_limitations"] = [
                verification_limitation(
                    reason="blocked_or_partial_without_details",
                    impact="The runner reported a blocked or partial result without structured recovery details.",
                    recovery_action="Review risks, stdout/stderr, and rerun with explicit recovery instructions.",
                    fallback_evidence=f"{run_dir / 'stdout.log'}; {run_dir / 'stderr.log'}",
                )
            ]
        report = report_contract_fields(report)
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.attach_operator_log_refs(run_dir, report)

    def attach_operator_log_refs(self, run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
        report = dict(report)
        try:
            compact_run_logs(run_dir)
        except Exception:
            return report
        return report
