from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .feishu_messages import render_delivery_breakdown, render_delivery_status, render_task_tree_status
from .models import AgentRunStatus, RunMode, TaskKind
from .services.delivery_service import DeliveryService


def command_coding_analyze(host: Any, raw_args: str) -> str:
    return command_coding_breakdown(host, raw_args)


def command_coding_breakdown(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供要拆解的任务 ID。用法：/coding breakdown <task_id>"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    try:
        result = host.start_run(task_id, mode=RunMode.DECOMPOSITION)
    except ValueError as exc:
        return str(exc)
    report = result.get("report") or {}
    if str(report.get("status") or "") != AgentRunStatus.SUCCEEDED.value:
        return host._format_decomposition_blocked_message(task_id, result)
    host.ledger.update_task_session(task_id, {"decomposition": DeliveryService.decomposition_for_session(report)})
    host.ledger.update_task_hierarchy(
        task_id,
        task_kind=TaskKind.REQUIREMENT.value,
        root_task_id=task_id,
        parent_task_id=None,
        dependency_task_ids=[],
    )
    return render_delivery_breakdown(task_id=task_id, report=report)


def command_coding_delivery_status(
    host: Any,
    *,
    task_id: str,
    task: dict[str, Any],
    tree_view: bool,
) -> str:
    children = host.ledger.list_child_tasks(task_id)
    if tree_view:
        return render_task_tree_status(parent=task, children=children)
    projection = host.delivery_service.status_projection(task, children)
    return render_delivery_status(**projection.as_render_kwargs())


def command_coding_run_next(host: Any, raw_args: str) -> str:
    args = raw_args.split()
    task_id = next((part for part in args if not part.startswith("--")), "")
    if not task_id:
        return "请提供父级需求任务 ID。用法：/coding run <task_id> --next"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    children = host.ledger.list_child_tasks(task_id)
    decision = host.delivery_service.run_next_decision(task, children)
    if decision.error == "not_requirement":
        return f"[{task_id}] 不是父级需求任务；请直接运行该执行任务。"
    if not decision.child:
        if decision.should_rollup:
            host._rollup_requirement_status(task_id)
        return f"[{task_id}] 暂无可运行的子任务。请查看 /coding status {task_id} --tree。"
    message = host.command_coding_implement(decision.child["task_id"])
    if decision.should_rollup:
        host._rollup_requirement_status(task_id)
    return f"[{task_id}] 已选择下一个可执行任务：{decision.child['task_id']}\n\n{message}"


def command_coding_approve_breakdown(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供要确认拆解的任务 ID。用法：/coding approve-breakdown <task_id>"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    decomposition = (task.get("task_session") or {}).get("decomposition") or {}
    if not decomposition:
        return f"[{task_id}] 还没有拆解方案。请先发送 /coding breakdown {task_id}。"
    if not bool(decomposition.get("materialization_allowed")):
        questions = "\n".join(f"- {item}" for item in decomposition.get("open_questions") or [])
        detail = f"\n{questions}" if questions else ""
        return f"[{task_id}] 拆解方案仍有待澄清问题，暂不能确认。{detail}"
    host.ledger.append_human_decision(
        task_id,
        {
            "type": "breakdown_approved",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return f"[{task_id}] 已确认拆解方案。下一步发送 /coding materialize {task_id} 生成执行任务。"


def command_coding_materialize(host: Any, raw_args: str) -> str:
    task_id = raw_args.strip()
    if not task_id:
        return "请提供要生成执行任务的需求 ID。用法：/coding materialize <task_id>"
    task = host.ledger.get_task(task_id)
    if not task:
        return f"未找到任务：{task_id}"
    if not DeliveryService.breakdown_is_approved(task):
        return f"[{task_id}] 拆解方案还未确认。请先发送 /coding approve-breakdown {task_id}。"
    decomposition = (task.get("task_session") or {}).get("decomposition") or {}
    if not bool(decomposition.get("materialization_allowed")):
        return f"[{task_id}] 拆解方案尚未允许生成执行任务，请先补充缺失信息并重新拆解。"
    try:
        children = materialize_execution_tasks(host, task)
    except ValueError as exc:
        return f"[{task_id}] 拆解方案不能生成执行任务：{exc}。请重新拆解。"
    if not children:
        return f"[{task_id}] 拆解方案里没有可生成的执行任务，请重新拆解。"
    return f"[{task_id}] 已生成 {len(children)} 个执行任务。\n" + "\n".join(
        f"- {child['task_id']}：{child['requirement_summary']}" for child in children
    )


def materialize_execution_tasks(host: Any, task: dict[str, Any]) -> list[dict[str, Any]]:
    existing_children = host.ledger.list_child_tasks(str(task["task_id"]))
    result = host.delivery_service.materialize_execution_tasks(
        task,
        existing_children=existing_children,
        create_child_task=lambda spec: host.ledger.create_task(**spec.as_create_task_kwargs()),
        get_child_task=host.ledger.get_task,
    )
    if result.errors:
        raise ValueError("; ".join(result.errors))
    return result.children
