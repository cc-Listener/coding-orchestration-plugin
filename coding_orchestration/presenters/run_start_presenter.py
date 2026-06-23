from __future__ import annotations

from typing import Any

from ..models import RunMode, task_status_display


def implementation_started_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已收到确认，开始实现。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：会把已确认计划交给 Codex，并在隔离工作区执行；不会自动进入测试、合并或发布。"
    )


def qa_started_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已开始 QA。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：本次 QA 由人工显式触发。完成后会自动回传结果，但不会自动 merge-test 或发布。"
    )


def implementation_blocked_before_plan_ready_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已拦截实现确认，但当前任务还不能开始开发。\n"
        f"状态：{task_status_display(task.get('status'))}\n"
        "必须先完成计划，并由你确认计划完整度和正确性后，才能开始实现。"
    )


def plan_only_started_message(task: dict[str, Any]) -> str:
    return (
        f"[{task['task_id']}] 已开始整理计划。\n"
        f"项目：{task.get('project_path') or '未确定'}\n"
        "说明：Codex 正在后台生成计划；完成后会自动回传结果。"
    )


def plan_only_already_running_message(task: dict[str, Any]) -> str:
    return active_run_already_running_message(task, requested_mode=RunMode.PLAN_ONLY.value)


def cannot_start_run_message(task: dict[str, Any], *, mode: RunMode, reason: str) -> str:
    task_id = str(task.get("task_id") or "unknown")
    return (
        f"[{task_id}] 当前状态为 {task_status_display(task.get('status'))}，不能启动{run_mode_user_label(mode)}执行。\n"
        f"原因：{reason}\n"
        "恢复动作：如需重新处理，请先重新整理计划或创建新的开发任务后再启动。"
    )


def active_run_already_running_message(task: dict[str, Any], *, requested_mode: str | None = None) -> str:
    session = task.get("task_session") or {}
    runner = session.get("runner") or {}
    active_run_id = runner.get("active_run_id") or "未记录"
    active_mode = run_mode_user_label(runner.get("active_mode") or runner.get("last_requested_mode"))
    task_id = task["task_id"]
    requested_label = run_mode_user_label(requested_mode)
    action_text = (
        f"未重复启动{requested_label}。"
        if requested_mode
        else "确认词已识别为当前执行的续接，但执行仍在进行，未启动新动作。"
    )
    return (
        f"[{task_id}] 当前已有执行正在进行，{action_text}\n"
        f"状态：{task_status_display(task.get('status'))}\n"
        f"当前执行：{active_run_id}\n"
        f"执行模式：{active_mode}\n"
        f"恢复动作：等待完成回传；如果确认卡住，先发送 /coding status {task_id} 查看详情，必要时再 /coding cancel {task_id} 后重试。"
    )


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
