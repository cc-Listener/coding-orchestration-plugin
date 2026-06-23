from __future__ import annotations

from typing import Any


def missing_feedback_media_message(task: dict[str, Any], action: str) -> str:
    task_id = task.get("task_id") or "unknown"
    return (
        f"[{task_id}] 未启动 Codex：检测到图片占位 [Image]，但图片未捕获，Hermes 没有拿到可访问图片。\n"
        f"请重发图片或图片链接，或补充文字描述后再发送 /coding {action} <反馈>。"
    )


def plan_feedback_received_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已收到计划反馈，重新整理计划。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：反馈已记录，并会带入下一轮计划；不会直接改代码。"
    )


def blocked_plan_feedback_received_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已收到受阻计划的补充信息，重新整理计划。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：上一次计划仍受阻，本次反馈会作为计划补充重新分析；不会直接开始实现。"
    )


def requirement_change_received_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已收到需求变更，重新分析变更影响。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：需求变更已记录；本轮只做影响分析和计划更新，不直接开始修复。"
    )


def requirement_change_queued_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已记录需求变更，但当前任务仍在执行。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：为避免并发修改，暂不启动新的计划；请等待当前执行结束后再次发送 /coding change，或先取消当前执行。"
    )


def implementation_feedback_received_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已收到修复反馈，开始修复。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：反馈已记录；会复用该任务最近一次实现工作区继续处理。"
    )


def runtime_feedback_received_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 任务正在运行，已记录本次反馈。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：反馈已记录；当前执行不会并发重启，后续重新整理计划或修复时会带入这次补充。"
    )


def human_clarification_received_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已收到补充信息，仍需要继续确认。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：补充已记录；请在项目或来源信息明确后重新整理计划。"
    )


def human_clarification_project_resolved_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已补充项目上下文，开始整理计划。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：项目上下文已记录；本轮补充会带入计划。"
    )
