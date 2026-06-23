from __future__ import annotations

from typing import Any

from ..models import task_status_display


def prepare_merge_test_ready_message(task_id: str, task: dict[str, Any]) -> str:
    return (
        f"[{task_id}] 已切换为等待人工执行 merge test。\n"
        f"项目目录：{task.get('project_path') or '未确定'}\n"
        f"下一步：确认后发送 /coding merge-test {task_id}，系统会基于上一次实现上下文执行 merge-test；发布测试环境仍然人工。"
    )


def prepare_merge_test_invalid_status_message(task_id: str, task: dict[str, Any]) -> str:
    return f"[{task_id}] 当前状态是 {task_status_display(task.get('status'))}，还不能准备 merge-test。"


def merge_test_blocked_validation_message(task_id: str, assessment: dict[str, Any]) -> str:
    return (
        f"[{task_id}] 当前验证证据不足，暂不能 merge-test。\n"
        f"影响：{assessment.get('impact') or '暂不能证明该受阻任务已安全完成实现。'}\n"
        f"建议：{assessment.get('recovery_action') or '先恢复实现，或补齐结构化报告、工作区和执行上下文后重试。'}"
    )


def merge_test_invalid_status_message(task: dict[str, Any]) -> str:
    task_id = str(task.get("task_id") or "")
    return f"[{task_id}] 当前状态是 {task_status_display(task.get('status'))}，还不能 merge-test。"


def merge_test_missing_workspace_message(task: dict[str, Any]) -> str:
    task_id = str(task.get("task_id") or "")
    return f"[{task_id}] 未找到实现工作区，无法基于上一次实现上下文执行 merge-test。"


def blocked_merge_test_risk_confirmation_message(task_id: str, assessment: dict[str, Any]) -> str:
    lines = [
        f"[{task_id}] 验证证据还不完整，但可以由你确认风险后继续 merge-test。",
        f"影响：{assessment.get('impact') or '缺少完整自动验证或结构化证据'}",
        f"建议：{assessment.get('recovery_action') or '补齐证据或重跑 implementation'}",
    ]
    fallback = str(assessment.get("fallback_evidence") or "").strip()
    if fallback:
        lines.append(fallback_evidence_user_line())
    lines.extend(
        [
            f"继续执行：/coding merge-test {task_id} --accept-risk",
            "回复“确认”会继续；回复“取消”会放弃本次继续动作。",
        ]
    )
    return "\n".join(lines)


def blocked_merge_test_release_note(release: dict[str, Any]) -> str:
    if release.get("accepted_risk"):
        lines = ["说明：已按你的风险确认继续 merge-test。"]
    else:
        lines = ["说明：已基于 Codex 给出的验证说明继续 merge-test。"]
    impact = str(release.get("impact") or "").strip()
    if impact:
        lines.append(f"影响：{impact}")
    recovery_action = str(release.get("recovery_action") or "").strip()
    if recovery_action:
        lines.append(f"建议：{recovery_action}")
    fallback = str(release.get("fallback_evidence") or "").strip()
    if fallback:
        lines.append(fallback_evidence_user_line())
    return "\n".join(lines)


def fallback_evidence_user_line() -> str:
    return "替代证据：已有运行记录可供核对。"


def merge_test_qa_risk_confirmation_message(
    task_id: str,
    qa_evidence: dict[str, str],
    *,
    include_reply_hint: bool = True,
) -> str:
    lines = [
        f"[{task_id}] 最近一次 QA 证据不够完整，继续 merge-test 需要你确认。",
        f"影响：{qa_evidence.get('impact') or '缺少可信 QA 通过证据'}",
        f"建议：{qa_evidence.get('recovery_action') or '重新运行 QA，或确认风险后继续'}",
        f"继续执行：/coding merge-test {task_id} --confirm-qa-risk",
    ]
    if include_reply_hint:
        lines.append("回复“确认”继续，或回复“取消”放弃。")
    return "\n".join(lines)


def merge_test_started_message(task: dict[str, Any]) -> str:
    task_id = task["task_id"]
    session = task.get("task_session") or {}
    return (
        f"[{task_id}] 已开始 merge-test。\n"
        f"源分支：{session.get('source_branch') or '未记录'}\n"
        "目标分支：test\n"
        "说明：会基于上一次实现上下文执行合入测试；发布仍然人工。"
    )
