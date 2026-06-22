from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import gateway_command_controller, run_start_presenter
from .models import RunMode, TaskPhase, TaskStatus


HANDLED_BY_CODING_ORCHESTRATION = {"action": "skip", "reason": "handled_by_coding_orchestration"}


def handle_gateway_custom_route(
    host: Any,
    route: gateway_command_controller.GatewayCommandRoute,
    *,
    text: str,
    event: Any,
    gateway: Any,
) -> dict[str, str] | None:
    if route.reply_mode != gateway_command_controller.GATEWAY_REPLY_CUSTOM:
        return None
    raw_args = route.raw_args
    handler_key = route.handler_key
    if handler_key == "create_task":
        return _handle_task_creation(host, raw_args, event, gateway)
    if handler_key == "continue":
        return _reply(host, gateway, event, host._continue_active_task(raw_args, event, gateway))
    if handler_key == "change":
        return _reply(host, gateway, event, host._change_active_task(raw_args, event, gateway))
    if handler_key == "bugfix":
        return _reply(host, gateway, event, host._bugfix_active_task(raw_args, event, gateway))
    if handler_key == "run":
        return _handle_plan_run(host, route, event, gateway)
    if handler_key in {"analyze", "breakdown"}:
        task_id = host._gateway_command_task_id(route, event)
        return _reply(host, gateway, event, host.command_coding_breakdown(task_id))
    if handler_key == "approve_breakdown":
        task_id = host._gateway_command_task_id(route, event)
        return _reply(host, gateway, event, host.command_coding_approve_breakdown(task_id))
    if handler_key == "materialize":
        task_id = host._gateway_command_task_id(route, event)
        return _reply(host, gateway, event, host.command_coding_materialize(task_id))
    if handler_key == "implement":
        return _handle_implementation(host, route, text, event, gateway)
    if handler_key == "qa":
        return _handle_qa(host, route, text, event, gateway)
    if handler_key == "prepare_merge_test":
        return _handle_prepare_merge_test(host, route, event, gateway)
    if handler_key == "merge_test":
        return _handle_merge_test(host, route, event, gateway)
    return None


def _reply(host: Any, gateway: Any, event: Any, message: str) -> dict[str, str]:
    host._reply_if_possible(gateway, event, message)
    return dict(HANDLED_BY_CODING_ORCHESTRATION)


def _handle_task_creation(host: Any, raw_args: str, event: Any, gateway: Any) -> dict[str, str]:
    source_context = host._read_source_context(raw_args, gateway)
    validation_error = host._task_creation_validation_error(raw_args, source_context)
    if validation_error:
        return _reply(host, gateway, event, validation_error)
    created = host._create_task_from_text(
        raw_args,
        auto_plan_on_ready=True,
        source_context=source_context,
        event=event,
    )
    host._reply_if_possible(gateway, event, created.message)
    if created.auto_plan_started:
        host._start_background_plan_only(created.task_id, gateway, event)
    elif created.auto_implementation_started:
        host._start_background_implementation(created.task_id, gateway, event)
    return dict(HANDLED_BY_CODING_ORCHESTRATION)


def _handle_plan_run(
    host: Any,
    route: gateway_command_controller.GatewayCommandRoute,
    event: Any,
    gateway: Any,
) -> dict[str, str]:
    task_id = host._gateway_command_task_id(route, event)
    task = host.ledger.get_task(task_id) if task_id else None
    if task is None:
        message = f"未找到任务：{task_id}" if task_id else "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。"
        return _reply(host, gateway, event, message)
    if host._task_is_cancelled(task):
        return _reply(host, gateway, event, host._cancelled_task_message(task))
    task = host._apply_active_project_to_task_if_missing(task, event)
    if str(task.get("status") or "") == TaskStatus.RUNNING.value:
        return _reply(host, gateway, event, run_start_presenter.plan_only_already_running_message(task))
    host._reply_if_possible(gateway, event, run_start_presenter.plan_only_started_message(task))
    host._start_background_plan_only(task_id, gateway, event)
    return dict(HANDLED_BY_CODING_ORCHESTRATION)


def _handle_implementation(
    host: Any,
    route: gateway_command_controller.GatewayCommandRoute,
    text: str,
    event: Any,
    gateway: Any,
) -> dict[str, str]:
    task_id = host._gateway_command_task_id(route, event)
    task = host.ledger.get_task(task_id) if task_id else None
    if task is None:
        return _reply(gateway=gateway, event=event, host=host, message="请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。")
    if host._task_is_cancelled(task):
        return _reply(host, gateway, event, host._cancelled_task_message(task))
    task = host._apply_active_project_to_task_if_missing(task, event)
    if not host._task_is_plan_ready_for_implementation(task):
        host._record_implementation_confirmation_before_plan_ready(task_id, text, event)
        return _reply(host, gateway, event, run_start_presenter.implementation_blocked_before_plan_ready_message(task))
    host._record_implementation_confirmation(task_id, text, event)
    host._reply_if_possible(gateway, event, run_start_presenter.implementation_started_message(task))
    host._start_background_implementation(task_id, gateway, event)
    return dict(HANDLED_BY_CODING_ORCHESTRATION)


def _handle_qa(
    host: Any,
    route: gateway_command_controller.GatewayCommandRoute,
    text: str,
    event: Any,
    gateway: Any,
) -> dict[str, str]:
    task_id = host._gateway_command_task_id(route, event)
    task = host.ledger.get_task(task_id) if task_id else None
    if task is None:
        return _reply(host, gateway, event, "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。")
    task = host._apply_active_project_to_task_if_missing(task, event)
    blocked = host._qa_start_blocker(task)
    if blocked:
        return _reply(host, gateway, event, blocked)
    host._record_qa_request(task_id, text, event)
    host._reply_if_possible(gateway, event, run_start_presenter.qa_started_message(task))
    host._start_background_qa(task_id, gateway, event)
    return dict(HANDLED_BY_CODING_ORCHESTRATION)


def _handle_prepare_merge_test(
    host: Any,
    route: gateway_command_controller.GatewayCommandRoute,
    event: Any,
    gateway: Any,
) -> dict[str, str]:
    task_id = host._gateway_command_task_id(route, event)
    task = host.ledger.get_task(task_id) if task_id else None
    assessment = (
        host._blocked_task_merge_test_assessment(task)
        if task is not None and task.get("status") == TaskStatus.BLOCKED.value
        else {}
    )
    message = host.command_prepare_merge_test(task_id)
    if assessment.get("mergeable") and assessment.get("requires_acceptance"):
        host._store_pending_action_for_event(
            event,
            task_id=task_id,
            action="merge_test_accept_risk",
            command_text=f"/coding merge-test {task_id} --accept-risk",
            reason=str(assessment.get("impact") or "blocked task merge-test 需要人工接受风险"),
            mode=RunMode.MERGE_TEST.value,
        )
    return _reply(host, gateway, event, message)


def _handle_merge_test(
    host: Any,
    route: gateway_command_controller.GatewayCommandRoute,
    event: Any,
    gateway: Any,
) -> dict[str, str]:
    parsed_args = gateway_command_controller.parse_merge_test_command_args(
        route.raw_args,
        host._active_task_id_for_event(event),
    )
    task_id = parsed_args.task_id
    task = host.ledger.get_task(task_id) if task_id else None
    if task is None:
        return _reply(host, gateway, event, "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。")
    assessment = host._blocked_task_merge_test_assessment(task)
    if assessment.get("requires_acceptance") and not parsed_args.accept_risk:
        host._store_pending_action_for_event(
            event,
            task_id=task_id,
            action="merge_test_accept_risk",
            command_text=f"/coding merge-test {task_id} --accept-risk",
            reason=str(assessment.get("impact") or "blocked task merge-test 需要人工接受风险"),
            mode=RunMode.MERGE_TEST.value,
        )
        return _reply(host, gateway, event, host._blocked_merge_test_risk_confirmation_message(task_id, assessment))
    release = host._release_blocked_task_for_merge_test_if_allowed(task, accept_risk=parsed_args.accept_risk)
    if release:
        task = host.ledger.get_task(task_id) or task
    blocked = host._merge_test_blocker(task)
    if blocked:
        return _reply(host, gateway, event, blocked)
    qa_evidence = host._qa_evidence_for_merge_test(task)
    if qa_evidence.get("requires_confirmation") == "true" and not parsed_args.confirm_qa_risk:
        host._store_pending_action_for_event(
            event,
            task_id=task_id,
            action="merge_test_qa_risk",
            command_text=f"/coding merge-test {task_id} --confirm-qa-risk",
            reason=str(qa_evidence.get("impact") or "merge-test 存在 QA 风险，需要人工确认"),
            mode=RunMode.MERGE_TEST.value,
        )
        return _reply(host, gateway, event, host._merge_test_qa_risk_confirmation_message(task_id, qa_evidence))
    host.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
    host.ledger.append_merge_record(
        task_id,
        {
            "type": "merge_test_requested",
            "status": "running",
            "target_branch": "test",
            "qa_evidence": qa_evidence,
            "blocked_release": release,
            "gateway_source": host._event_source_for_ledger(event),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    started_message = host._merge_test_started_message(task)
    if release:
        started_message = f"{started_message}\n{host._blocked_merge_test_release_note(release)}"
    host._reply_if_possible(gateway, event, started_message)
    host._start_background_merge_test(task_id, gateway, event)
    return dict(HANDLED_BY_CODING_ORCHESTRATION)
