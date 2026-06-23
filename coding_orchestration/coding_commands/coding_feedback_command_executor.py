from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..presenters import feedback_presenter
from ..models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from ..project.project_resolver import normalize_text as normalize_project_text
from ..services import RunService


def command_coding_continue(host: Any, raw_args: str) -> str:
    return "当前会话没有绑定任务；请在飞书里使用 /coding continue <反馈>，或使用 /coding run <task_id>。"


def command_coding_change(host: Any, raw_args: str) -> str:
    return "当前会话没有绑定任务；请在飞书里使用 /coding change <反馈>。"


def command_coding_bugfix(host: Any, raw_args: str) -> str:
    return "当前会话没有绑定任务；请在飞书里使用 /coding bugfix <反馈>，或使用 /coding implement <task_id>。"


def continue_active_task(host: Any, raw_args: str, event: Any, gateway: Any) -> str:
    task = host._active_task_for_event(event)
    if task is None:
        return "未找到当前开发任务，请先使用 /coding use <task_id>。"
    if host._task_is_cancelled(task):
        return host._cancelled_task_message(task)
    if not raw_args.strip():
        return "请在 /coding continue 后提供补充内容。"
    if host._mentions_image_placeholder_without_media(raw_args, event):
        return feedback_presenter.missing_feedback_media_message(task, "continue")
    status = str(task.get("status") or "")
    if status == TaskStatus.RUNNING.value:
        record_runtime_feedback(host, task, raw_args, event)
        return feedback_presenter.runtime_feedback_received_message(task)
    if not task.get("project_path"):
        project_resolved = record_human_clarification(host, task, raw_args, event)
        updated_task = host.ledger.get_task(task["task_id"]) or task
        if project_resolved:
            host._start_background_plan_only(task["task_id"], gateway, event)
            return feedback_presenter.human_clarification_project_resolved_message(updated_task)
        return feedback_presenter.human_clarification_received_message(updated_task)
    if status == TaskStatus.NEEDS_HUMAN.value:
        project_resolved = record_human_clarification(host, task, raw_args, event)
        updated_task = host.ledger.get_task(task["task_id"]) or task
        if project_resolved:
            host._start_background_plan_only(task["task_id"], gateway, event)
            return feedback_presenter.human_clarification_project_resolved_message(updated_task)
        return feedback_presenter.human_clarification_received_message(updated_task)
    record_plan_feedback(host, task, raw_args, event)
    host._start_background_plan_only(task["task_id"], gateway, event)
    return feedback_presenter.plan_feedback_received_message(task)


def change_active_task(host: Any, raw_args: str, event: Any, gateway: Any) -> str:
    task = host._active_task_for_event(event)
    if task is None:
        return "未找到当前开发任务，请先使用 /coding use <task_id>。"
    if host._task_is_cancelled(task):
        return host._cancelled_task_message(task)
    if not raw_args.strip():
        return "请在 /coding change 后提供需求变更内容。"
    if host._mentions_image_placeholder_without_media(raw_args, event):
        return feedback_presenter.missing_feedback_media_message(task, "change")
    record_requirement_change(host, task, raw_args, event)
    status = str(task.get("status") or "")
    if status == TaskStatus.RUNNING.value:
        return feedback_presenter.requirement_change_queued_message(task)
    host._start_background_plan_only(task["task_id"], gateway, event)
    return feedback_presenter.requirement_change_received_message(task)


def bugfix_active_task(host: Any, raw_args: str, event: Any, gateway: Any) -> str:
    task = host._active_task_for_event(event)
    if task is None:
        return "未找到当前开发任务，请先使用 /coding use <task_id>。"
    if host._task_is_cancelled(task):
        return host._cancelled_task_message(task)
    if not raw_args.strip():
        return "请在 /coding bugfix 后提供修复反馈。"
    if host._mentions_image_placeholder_without_media(raw_args, event):
        return feedback_presenter.missing_feedback_media_message(task, "bugfix")
    task = host._reopen_merged_test_task_for_bugfix_if_needed(task, event)
    if bugfix_feedback_should_replan(task, raw_args):
        record_plan_feedback(host, task, raw_args, event)
        host._start_background_plan_only(task["task_id"], gateway, event)
        if bugfix_feedback_should_replan_after_blocked_plan(task):
            return feedback_presenter.blocked_plan_feedback_received_message(task)
        return feedback_presenter.plan_feedback_received_message(task)
    record_implementation_feedback(host, task, raw_args, event)
    host._start_background_implementation(task["task_id"], gateway, event)
    return feedback_presenter.implementation_feedback_received_message(task)


def bugfix_feedback_should_replan(task: dict[str, Any], feedback: str) -> bool:
    if bugfix_feedback_should_replan_after_blocked_plan(task):
        return True
    status = str(task.get("status") or "")
    if status != TaskStatus.PLANNED.value:
        return False
    if task_has_post_plan_run(task):
        return False
    text = normalize_project_text(feedback).lower()
    if any(
        marker in text
        for marker in (
            "源分支",
            "source branch",
            "worktree",
            "session",
            "截图",
            "图片",
            "样式",
            "展示",
            "调整",
            "修改",
            "修复",
            "忽略",
            "git",
            "文件",
        )
    ):
        return False
    phase = str(task.get("phase") or "")
    if phase in {TaskPhase.DRAFT.value, TaskPhase.PLANNING.value}:
        return True
    return any(
        marker in text
        for marker in (
            "plan",
            "计划",
            "重新制定",
            "补充",
            "需求",
            "字段",
            "schema",
            "swagger",
            "api",
        )
    )


def task_has_post_plan_run(task: dict[str, Any]) -> bool:
    for run in task.get("agent_runs") or []:
        if str(run.get("mode") or "") in {
            RunMode.IMPLEMENTATION.value,
            RunMode.QA.value,
            RunMode.MERGE_TEST.value,
        }:
            return True
    return False


def bugfix_feedback_should_replan_after_blocked_plan(task: dict[str, Any]) -> bool:
    if str(task.get("status") or "") != TaskStatus.BLOCKED.value:
        return False
    runs = list(task.get("agent_runs") or [])
    if not runs:
        return False
    latest_run = runs[-1]
    if str(latest_run.get("mode") or "") != RunMode.PLAN_ONLY.value:
        return False
    if str(latest_run.get("status") or "") != AgentRunStatus.BLOCKED.value:
        return False
    return not _task_is_plan_ready_for_implementation(task)


def _task_is_plan_ready_for_implementation(task: dict[str, Any]) -> bool:
    return RunService.task_is_plan_ready_for_implementation(task)


def record_plan_feedback(host: Any, task: dict[str, Any], text: str, event: Any) -> None:
    host.ledger.update_phase(task["task_id"], TaskPhase.PLAN_REVISION.value)
    record_task_feedback(
        host,
        task,
        text,
        event,
        decision_type="plan_feedback",
        title_prefix="计划反馈",
        summary_heading="人工计划反馈",
        tags=["requirement", "plan_feedback", "draft"],
    )


def record_requirement_change(host: Any, task: dict[str, Any], text: str, event: Any) -> None:
    host.ledger.update_phase(task["task_id"], TaskPhase.PLAN_REVISION.value)
    record_task_feedback(
        host,
        task,
        text,
        event,
        decision_type="requirement_change",
        title_prefix="需求变更",
        summary_heading="人工需求变更",
        tags=["requirement", "requirement_change", "draft"],
    )


def record_implementation_feedback(host: Any, task: dict[str, Any], text: str, event: Any) -> None:
    host.ledger.update_phase(task["task_id"], TaskPhase.BUGFIXING.value)
    record_task_feedback(
        host,
        task,
        text,
        event,
        decision_type="implementation_feedback",
        title_prefix="实现反馈",
        summary_heading="人工实现反馈",
        tags=["requirement", "implementation_feedback", "bugfix", "draft"],
    )


def record_runtime_feedback(host: Any, task: dict[str, Any], text: str, event: Any) -> None:
    record_task_feedback(
        host,
        task,
        text,
        event,
        decision_type="runtime_feedback",
        title_prefix="运行中反馈",
        summary_heading="运行中反馈",
        tags=["requirement", "runtime_feedback", "draft"],
    )


def record_human_clarification(host: Any, task: dict[str, Any], text: str, event: Any) -> Any:
    record_task_feedback(
        host,
        task,
        text,
        event,
        decision_type="human_clarification",
        title_prefix="人工补充",
        summary_heading="人工补充",
        tags=["requirement", "human_clarification", "draft"],
    )
    updated_task = host.ledger.get_task(task["task_id"]) or task
    return host._apply_project_clarification(updated_task, text)


def record_task_feedback(
    host: Any,
    task: dict[str, Any],
    text: str,
    event: Any,
    *,
    decision_type: str,
    title_prefix: str,
    summary_heading: str,
    tags: list[str],
) -> None:
    task_id = task["task_id"]
    feedback = normalize_project_text(text)
    now = datetime.now(timezone.utc).isoformat()
    media = host._event_media_for_ledger(event)
    decision = {
        "type": decision_type,
        "text": feedback,
        "gateway_source": host._event_source_for_ledger(event),
        "created_at": now,
    }
    if media:
        decision["media"] = media
    host.ledger.append_human_decision(task_id, decision)
    feedback_body = host._append_media_description(feedback, media)
    updated_summary = (
        f"{str(task.get('requirement_summary') or '').rstrip()}\n\n"
        f"## {summary_heading} {now}\n"
        f"{feedback_body}"
    ).strip()
    host.ledger.update_requirement_summary(task_id, updated_summary)
    source = task.get("source") or {}
    feedback_ref = host.wiki.upsert(
        {
            "kind": "draft_knowledge",
            "title": f"{title_prefix} {task_id}",
            "body": feedback_body,
            "source_refs": host._draft_knowledge_source_refs(task_id, {}, event),
            "project": source.get("project_name"),
            "module": None,
            "tags": tags,
            "confidence": "medium",
            "status": "draft",
        },
        options={"dedupe_key": f"{task_id}:{decision_type}:{len(task.get('human_decisions') or []) + 1}"},
    )
    refs = list(task.get("llm_wiki_refs") or [])
    refs.append(feedback_ref)
    host.ledger.replace_llm_wiki_refs(task_id, refs)
