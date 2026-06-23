from __future__ import annotations

from typing import Any, Callable

from . import background_run_notifier
from ..models import RunMode
from ..presenters import run_completion_presenter


def start_background_plan_only(host: Any, task_id: str, gateway: Any, event: Any) -> None:
    _start_background_run(host, task_id, gateway, event, mode=RunMode.PLAN_ONLY, target=run_plan_only_and_notify)


def start_background_implementation(host: Any, task_id: str, gateway: Any, event: Any) -> None:
    _start_background_run(
        host,
        task_id,
        gateway,
        event,
        mode=RunMode.IMPLEMENTATION,
        target=run_implementation_and_notify,
    )


def start_background_qa(host: Any, task_id: str, gateway: Any, event: Any) -> None:
    _start_background_run(host, task_id, gateway, event, mode=RunMode.QA, target=run_qa_and_notify)


def start_background_merge_test(host: Any, task_id: str, gateway: Any, event: Any) -> None:
    _start_background_run(
        host,
        task_id,
        gateway,
        event,
        mode=RunMode.MERGE_TEST,
        target=run_merge_test_and_notify,
    )


def run_plan_only_and_notify(host: Any, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
    mode = RunMode.PLAN_ONLY
    _run_and_notify(
        host,
        task_id,
        gateway,
        event,
        loop,
        mode=mode,
        format_success_message=lambda result: run_completion_presenter.format_run_completion_message(task_id, result),
    )


def run_implementation_and_notify(host: Any, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
    mode = RunMode.IMPLEMENTATION
    _run_and_notify(
        host,
        task_id,
        gateway,
        event,
        loop,
        mode=mode,
        format_success_message=lambda result: (
            run_completion_presenter.format_stale_run_completion_message(task_id, result)
            if result.get("stale_completion")
            else run_completion_presenter.format_implementation_completion_message(task_id, result)
        ),
    )


def run_qa_and_notify(host: Any, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
    mode = RunMode.QA
    _run_and_notify(
        host,
        task_id,
        gateway,
        event,
        loop,
        mode=mode,
        format_success_message=lambda result: run_completion_presenter.format_qa_completion_message(task_id, result),
    )


def run_merge_test_and_notify(host: Any, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
    mode = RunMode.MERGE_TEST
    _run_and_notify(
        host,
        task_id,
        gateway,
        event,
        loop,
        mode=mode,
        after_success=lambda result: host._store_pending_action_from_merge_test_result(event, task_id, result),
        format_success_message=lambda result: run_completion_presenter.format_merge_test_completion_message(task_id, result),
    )


def _start_background_run(
    host: Any,
    task_id: str,
    gateway: Any,
    event: Any,
    *,
    mode: RunMode,
    target: Callable[[Any, str, Any, Any, Any | None], None],
) -> None:
    background_run_notifier.start_background_run(
        task_id,
        gateway,
        event,
        mode=mode,
        target=lambda task_id, gateway, event, loop: target(host, task_id, gateway, event, loop),
    )


def _run_and_notify(
    host: Any,
    task_id: str,
    gateway: Any,
    event: Any,
    loop: Any | None,
    *,
    mode: RunMode,
    format_success_message: Callable[[dict[str, Any]], str],
    after_success: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    background_run_notifier.run_and_notify(
        task_id,
        gateway,
        event,
        loop,
        mode=mode,
        execute=lambda: host._wait_for_background_run_completion(
            task_id,
            host.start_run(task_id, mode=mode),
            mode=mode,
        ),
        after_success=after_success,
        format_success_message=format_success_message,
        mark_failed=lambda exc: host._mark_background_run_failed(task_id, exc, mode=mode),
        record_notification=lambda result, reply: host._record_completion_notification(
            task_id,
            mode=mode,
            result=result,
            reply=reply,
        ),
    )
