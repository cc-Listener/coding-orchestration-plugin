from __future__ import annotations

from typing import Any

from .. import delivery_command_executor, task_status_presenter


def command_coding_status(host: Any, raw_args: str) -> str:
    args = raw_args.split()
    delivery_view = "--delivery" in args
    tree_view = "--tree" in args
    task_id = " ".join(arg for arg in args if not arg.startswith("--")).strip()
    if not task_id:
        return "请提供任务 ID。"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    reconciled = host._reconcile_completed_active_run(task_id, task=task)
    if reconciled:
        task = host.ledger.get_task(task_id) or task
        return "\n".join(
            [
                f"[{task_id}] 已自动回收后台执行：{reconciled['run_id']}",
                task_status_presenter.format_task_status_details(task, include_branch=False),
            ]
        )
    if delivery_view or tree_view:
        return delivery_command_executor.command_coding_delivery_status(
            host,
            task_id=task_id,
            task=task,
            tree_view=tree_view,
        )
    return task_status_presenter.format_task_status_details(task, include_branch=False)


def status_for_event(host: Any, raw_args: str, event: Any) -> str:
    args = raw_args.split()
    flags = [arg for arg in args if arg.startswith("--")]
    task_id = next((arg for arg in args if not arg.startswith("--")), "") or host._active_task_id_for_event(event) or ""
    if not task_id:
        return "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。"
    if flags:
        return command_coding_status(host, " ".join([task_id, *flags]))
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    reconciled = host._reconcile_completed_active_run(task_id, task=task)
    if reconciled:
        task = host.ledger.get_task(task_id) or task
        return "\n".join(
            [
                f"[{task_id}] 已自动回收后台执行：{reconciled['run_id']}",
                task_status_presenter.format_task_status_details(task, include_branch=True),
            ]
        )
    return task_status_presenter.format_task_status_details(task, include_branch=True)
