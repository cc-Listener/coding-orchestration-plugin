from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .feishu_copy import render_user_update
from .models import RunMode, TaskStatus, task_status_display
from .status_policy import run_status_details_from_report


def format_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
    artifacts = result.get("artifacts") or {}
    report = load_report_from_artifacts(artifacts)
    next_actions = completion_next_actions(report)
    next_actions.append("请人工确认计划完整度和正确性；确认后再开始实现。")
    risk_note = completion_risk_note(report)
    summary = completion_user_summary(report, artifacts, summary_limit=1800)

    details = run_status_details_from_report(report, RunMode.PLAN_ONLY)
    if not summary and (
        details.get("status_detail") == "completed_unstructured" or details.get("structured") is False
    ):
        stderr = read_text_excerpt(artifacts.get("stderr"), limit=1000)
        if stderr:
            summary = f"执行没有产出结构化计划摘要。\n执行错误摘要：{stderr}"

    return render_user_update(
        title="计划已生成",
        task_id=task_id,
        user_facing_summary=completion_user_summary_with_status(result, summary),
        next_actions=dedupe_texts(next_actions),
        risk_note=risk_note,
    )


def format_implementation_completion_message(task_id: str, result: dict[str, Any]) -> str:
    artifacts = result.get("artifacts") or {}
    report = load_report_from_artifacts(artifacts)
    next_actions = completion_next_actions(report)

    status = str(result.get("task_status") or "")
    if status == TaskStatus.READY_FOR_MERGE_TEST.value:
        next_actions.extend(
            (
                f"测试为可选项；需要继续 QA 时发送 /coding qa {task_id}。",
                f"如人工确认现有验证已足够，发送 /coding merge-test {task_id}。",
            )
        )
    elif bool(report.get("known_gaps")):
        next_actions.extend(
            (
                f"测试为可选项；需要补验证时发送 /coding qa {task_id}。",
                f"如人工接受已知缺口，再发送 /coding merge-test {task_id}。",
            )
        )
    next_actions.append("任务不会自动进入测试、合并或发布测试环境；QA 和 merge-test 都需要人工触发。")
    return render_user_update(
        title="实现已完成",
        task_id=task_id,
        user_facing_summary=completion_user_summary_with_status(
            result,
            completion_user_summary(report, artifacts, summary_limit=1600),
        ),
        next_actions=dedupe_texts(next_actions),
        risk_note=completion_risk_note(report),
    )


def format_qa_completion_message(task_id: str, result: dict[str, Any]) -> str:
    artifacts = result.get("artifacts") or {}
    report = load_report_from_artifacts(artifacts)
    summary = completion_user_summary(report, artifacts, summary_limit=1600)
    next_actions = completion_next_actions(report)
    qa_artifacts = report.get("qa_artifacts") or {}
    if qa_artifacts.get("report"):
        health_score = qa_health_score_from_report_path(qa_artifacts.get("report"))
        if health_score:
            summary = f"{summary}\nQA health score：{health_score}".strip()

    limitations = report.get("verification_limitations") or []
    if limitations:
        limitation_lines = []
        for item in limitations[:3]:
            if isinstance(item, dict):
                limitation_lines.append(f"{item.get('reason') or 'unknown'}：{item.get('recovery_action') or ''}")
        if limitation_lines:
            summary = f"{summary}\n已知缺口：\n" + "\n".join(f"- {item}" for item in limitation_lines)

    return render_user_update(
        title="QA 已完成",
        task_id=task_id,
        user_facing_summary=completion_user_summary_with_status(result, summary),
        next_actions=dedupe_texts(next_actions),
        risk_note=completion_risk_note(report),
    )


def format_stale_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
    summary = (
        f"旧{run_mode_user_label(result.get('mode') or 'agent')}执行已完成，但任务期间已有更新执行。"
        f"\n当前任务状态：{task_status_display(result.get('current_task_status'))}"
        "\n本次结果仅保留用于审计，不会回退当前任务状态。"
    )
    return render_user_update(
        title="旧执行已归档",
        task_id=task_id,
        user_facing_summary=summary,
        next_actions=[f"查看当前最新任务状态：/coding status {task_id}"],
    )


def format_merge_test_completion_message(task_id: str, result: dict[str, Any]) -> str:
    artifacts = result.get("artifacts") or {}
    report = load_report_from_artifacts(artifacts)
    next_actions = completion_next_actions(report)

    if bool(report.get("human_required")):
        next_actions.extend(
            (
                f"回复“确认”继续当前 merge-test，或直接发送 /coding merge-test {task_id}。",
                "本次 merge-test 尚未完成；Hermes 会优先续接待确认动作，不会把确认词交给 LLM rewrite。",
            )
        )
    else:
        next_actions.extend(
            (
                f"确认测试环境符合预期后，发送 /coding complete {task_id} 手动标记完成。",
                "已允许 merge/push test；发布测试环境仍需人工。merge-test 成功不代表 task 已完成。",
            )
        )
    return render_user_update(
        title="merge-test 已处理",
        task_id=task_id,
        user_facing_summary=completion_user_summary_with_status(
            result,
            completion_user_summary(report, artifacts, summary_limit=1600),
        ),
        next_actions=dedupe_texts(next_actions),
        risk_note=completion_risk_note(report),
    )


def load_report_from_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
    report_path = Path(str(artifacts.get("report") or ""))
    if not report_path.exists():
        return {}
    try:
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def completion_user_summary(report: dict[str, Any], artifacts: dict[str, Any], *, summary_limit: int) -> str:
    for value in (
        report.get("user_facing_summary"),
        report.get("summary_markdown"),
        read_text_excerpt(artifacts.get("summary"), limit=summary_limit),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def completion_user_summary_with_status(result: dict[str, Any], summary: str) -> str:
    status = task_status_display(result.get("task_status"))
    status_line = f"结果状态：{status}"
    summary = summary.strip()
    if summary:
        return f"{status_line}\n{summary}"
    return status_line


def completion_next_actions(report: dict[str, Any]) -> list[str]:
    return dedupe_texts(report.get("next_actions") or [])


def completion_risk_note(report: dict[str, Any]) -> str:
    risk_note = str(report.get("risk_note") or "").strip()
    if risk_note:
        return risk_note
    risks = [str(item).strip() for item in report.get("risks") or [] if str(item).strip()]
    return "\n".join(f"- {item}" for item in risks[:5])


def dedupe_texts(items: list[Any]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def read_text_excerpt(path_value: Any, *, limit: int) -> str:
    if not path_value:
        return ""
    path = Path(str(path_value))
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...（已截断，完整内容见 artifact）"


def qa_health_score_from_report_path(path_value: Any) -> str:
    path = Path(str(path_value))
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"health\s*score\s*[:：]\s*([0-9]+(?:\s*[-→>]+\s*[0-9]+)?)", text, flags=re.I)
    return match.group(1).strip() if match else ""


def run_mode_user_label(mode: RunMode | str | None) -> str:
    value = mode.value if isinstance(mode, RunMode) else str(mode or "").strip()
    labels = {
        RunMode.DECOMPOSITION.value: "需求拆解",
        RunMode.PLAN_ONLY.value: "整理计划",
        RunMode.IMPLEMENTATION.value: "实现",
        RunMode.QA.value: "QA 验证",
        RunMode.MERGE_TEST.value: "merge-test",
    }
    return labels.get(value, value or "未记录")
