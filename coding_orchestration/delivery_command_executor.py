from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .services.delivery_service import DeliveryService


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
