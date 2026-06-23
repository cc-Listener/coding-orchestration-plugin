from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import RunMode, agent_run_status_details


@dataclass(frozen=True)
class RunFailureReportProjection:
    status: str
    stderr: str
    summary: str
    report: dict[str, Any]


def _empty_qa_artifacts() -> dict[str, str]:
    return {"report": "", "baseline": "", "screenshots_dir": ""}


def build_runner_failed_report_payload(
    *,
    runner_name: str,
    mode: RunMode,
    error: Any,
    stdout_path: Any,
    stderr_path: Any,
    summary_path: Any,
) -> RunFailureReportProjection:
    mode = RunMode(mode)
    stderr = str(error)
    summary = f"Runner failed before producing a structured result: {stderr}"
    report = {
        "runner": runner_name,
        **agent_run_status_details("runner_failed", mode),
        "mode": mode.value,
        "summary_markdown": summary,
        "modified_files": [],
        "test_commands": [],
        "test_results": [],
        "risks": ["Runner crashed or failed before a structured report was produced."],
        "verification_limitations": [
            {
                "reason": "runner_exception",
                "impact": "The requested run did not execute to completion, so no implementation or verification result can be trusted.",
                "recovery_action": "Inspect stderr, fix the runner invocation or environment, then rerun the same task.",
                "fallback_evidence": str(stderr_path),
            }
        ],
        "human_required": True,
        "next_actions": ["Inspect runner stderr and rerun after correcting the runner failure."],
        "qa_artifacts": _empty_qa_artifacts(),
        "tested_commit": "",
        "raw_stdout_ref": str(stdout_path),
        "raw_stderr_ref": str(stderr_path),
        "summary_ref": str(summary_path),
    }
    return RunFailureReportProjection(status=str(report["status"]), stderr=stderr, summary=summary, report=report)


def build_checkpoint_failed_report_payload(
    *,
    runner_name: str,
    mode: RunMode,
    checkpoint: dict[str, Any],
    stderr_path: Any,
) -> RunFailureReportProjection:
    mode = RunMode(mode)
    stderr = str(checkpoint.get("error") or "source worktree has uncommitted changes")
    if mode == RunMode.MERGE_TEST:
        summary = "merge-test 未启动：实现工作区仍有未提交改动。"
        risk = "merge-test 前 source branch 必须已经由 Codex 按 Git Flow/Conventional Commit 规范提交干净。"
        impact = "merge-test run 未执行，避免把未提交实现改动用流程状态信息提交。"
        recovery_action = "让 Codex 根据实际 diff 创建符合规范的实现提交后，重新触发 merge-test。"
        next_actions = ["让 Codex 提交当前 implementation 改动后重新触发 merge-test。"]
    else:
        summary = "QA 未启动：实现工作区仍有未提交改动。"
        risk = "QA 前 source branch 必须已经由 Codex 按 Git Flow/Conventional Commit 规范提交干净。"
        impact = "QA run 未执行，当前缺少自动测试证据。"
        recovery_action = "让 Codex 根据实际 diff 创建符合规范的实现提交后，重新运行 QA。"
        next_actions = ["让 Codex 提交当前 implementation 改动后重新触发 QA；也可以人工判断后继续 merge-test。"]
    report = {
        "runner": runner_name,
        **agent_run_status_details("blocked", mode),
        "mode": mode.value,
        "summary_markdown": summary,
        "modified_files": [],
        "test_commands": [],
        "test_results": [],
        "risks": [risk],
        "verification_limitations": [
            {
                "reason": str(checkpoint.get("reason") or "implementation_commit_missing"),
                "impact": impact,
                "recovery_action": recovery_action,
                "fallback_evidence": str(stderr_path),
            }
        ],
        "human_required": True,
        "next_actions": next_actions,
        "qa_artifacts": _empty_qa_artifacts(),
        "tested_commit": "",
    }
    return RunFailureReportProjection(status=str(report["status"]), stderr=stderr, summary=summary, report=report)
