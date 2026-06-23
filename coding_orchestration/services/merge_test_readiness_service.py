from __future__ import annotations

from typing import Any

from .. import status_policy
from ..models import AgentRunStatus, RunMode, TaskStatus


def latest_implementation_run(task: dict[str, Any]) -> dict[str, Any] | None:
    for run in reversed(task.get("agent_runs") or []):
        if run.get("mode") == RunMode.IMPLEMENTATION.value:
            return run
    return None


def source_branch_for_blocked_merge_test(task: dict[str, Any], run: dict[str, Any]) -> str:
    session = task.get("task_session") or {}
    return str(session.get("source_branch") or run.get("source_branch") or "").strip()


def disallowed_blocked_merge_test_reason(run: dict[str, Any]) -> str:
    diff_guard = run.get("diff_guard") or {}
    if diff_guard.get("violations"):
        return "diff_guard_violation"
    return ""


def _artifact_value(run: dict[str, Any], *keys: str) -> str:
    artifact = run.get("artifact") or {}
    for key in keys:
        value = str(artifact.get(key) or "").strip()
        if value:
            return value
    return ""


def assess_blocked_merge_test(
    *,
    task: dict[str, Any],
    implementation_run: dict[str, Any] | None,
    has_merge_test_workspace: bool,
    source_branch: str,
    resume_session_id: str,
    report: dict[str, Any] | None,
    merge_test_workspace_path: str = "",
) -> dict[str, Any]:
    if str(task.get("status") or "") != TaskStatus.BLOCKED.value:
        return {"mergeable": False, "reason": "task_not_blocked"}

    run = implementation_run or {}
    if not run:
        return {
            "mergeable": False,
            "reason": "missing_implementation_run",
            "impact": "没有找到可用于继续的实现运行记录，无法证明代码已完成。",
            "recovery_action": "先重新执行 implementation，或补齐实现运行记录后重试。",
        }

    run_id = str(run.get("run_id") or "")
    run_status = str(run.get("status") or "")
    if run_status in {
        AgentRunStatus.RUNNER_FAILED.value,
        AgentRunStatus.FAILED.value,
        TaskStatus.FAILED.value,
    }:
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": run_id,
            "reason": f"implementation_{run_status}",
            "impact": "最近一次实现结果不可信，不能直接合入 test。",
            "recovery_action": "建议先恢复或重跑 implementation；如人工确认目标改动已经完成，可使用 --accept-risk 继续 merge-test。",
            "fallback_evidence": _artifact_value(run, "summary", "stderr"),
        }

    if not has_merge_test_workspace:
        return {
            "mergeable": False,
            "source_run_id": run_id,
            "reason": "missing_implementation_worktree",
            "impact": "没有找到可用于 merge-test 的实现工作区。",
            "recovery_action": "恢复实现工作区，或重新执行 implementation 后再 merge-test。",
        }

    if not source_branch:
        return {
            "mergeable": False,
            "source_run_id": run_id,
            "reason": "missing_source_branch",
            "impact": "没有找到可合入 test 的实现分支记录。",
            "recovery_action": "重新执行 implementation 创建实现分支，或补齐实现分支记录后重试。",
        }

    if not resume_session_id:
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": run_id,
            "reason": "missing_codex_session",
            "impact": "无法续接原 Codex 会话，继续 merge-test 时历史上下文可能不完整。",
            "recovery_action": "确认目标改动和工作区正确后，人工接受风险继续 merge-test。",
            "fallback_evidence": str(run.get("workspace_path") or merge_test_workspace_path or ""),
        }

    report = report if isinstance(report, dict) and report else {}
    if not report:
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": run_id,
            "reason": "missing_structured_report",
            "impact": "缺少结构化验证报告，只能基于现有运行记录做人工风险放行。",
            "recovery_action": "检查现有运行记录；如确认风险可接受，人工接受风险继续 merge-test。",
            "fallback_evidence": _artifact_value(run, "summary", "stdout", "stderr") or str(run.get("workspace_path") or ""),
        }

    report_status = str(report.get("status") or run_status)
    if report_status in {
        AgentRunStatus.RUNNER_FAILED.value,
        AgentRunStatus.FAILED.value,
        TaskStatus.FAILED.value,
    }:
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": run_id,
            "reason": f"report_{report_status}",
            "impact": "结构化验证报告显示运行失败，默认不合入 test；人工可在确认目标改动无误后覆盖风险。",
            "recovery_action": "建议先修复失败原因并重跑 implementation；如确认可接受，人工接受风险继续 merge-test。",
            "fallback_evidence": _artifact_value(run, "report"),
        }

    disallowed_reason = disallowed_blocked_merge_test_reason(run)
    if disallowed_reason:
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": run_id,
            "reason": disallowed_reason,
            "impact": "当前阻断风险较高，默认不合入 test；人工可在确认风险可接受后覆盖。",
            "recovery_action": "建议先处理阻断原因并重新执行 implementation；如确认可接受，人工接受风险继续 merge-test。",
            "fallback_evidence": _artifact_value(run, "report"),
        }

    if status_policy.implementation_report_explicitly_not_landed(report):
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": run_id,
            "reason": "implementation_not_landed",
            "impact": "结构化验证报告显示实现尚未形成可追踪提交，默认不合入 test；如果人工确认目标改动已完成，可覆盖风险。",
            "recovery_action": "先让 Codex 完成实现提交，或确认目标改动后人工接受风险继续 merge-test。",
            "fallback_evidence": _artifact_value(run, "report"),
        }

    readiness = report.get("merge_readiness") if isinstance(report.get("merge_readiness"), dict) else {}
    if not readiness:
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": run_id,
            "reason": "merge_readiness_missing",
            "impact": "结构化验证结论缺失，系统不能自动判断是否可继续。",
            "recovery_action": "续接 Codex 补齐验证结论，或人工确认后继续 merge-test。",
            "fallback_evidence": _artifact_value(run, "report"),
        }

    if readiness.get("ready") is True:
        return {
            "mergeable": True,
            "requires_acceptance": bool(readiness.get("required_confirmation")),
            "source_run_id": run_id,
            "reason": "codex_merge_readiness",
            "impact": str(readiness.get("risk_note") or "Codex 判断可继续 merge-test。"),
            "recovery_action": str(readiness.get("recovery_action") or "按 Codex 风险说明继续。"),
            "fallback_evidence": str(readiness.get("fallback_evidence") or ""),
        }

    return {
        "mergeable": False,
        "requires_acceptance": True,
        "source_run_id": run_id,
        "reason": str(readiness.get("reason") or "codex_merge_readiness_blocked"),
        "impact": str(readiness.get("risk_note") or readiness.get("impact") or "Codex 判断暂不应继续 merge-test。"),
        "recovery_action": str(readiness.get("recovery_action") or "按 Codex 风险说明处理后重试。"),
        "fallback_evidence": str(readiness.get("fallback_evidence") or ""),
    }
