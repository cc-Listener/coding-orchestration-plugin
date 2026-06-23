from __future__ import annotations

import asyncio
import inspect
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from ..models import RunMode


def current_event_loop_or_none() -> Any | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def start_background_run(
    task_id: str,
    gateway: Any,
    event: Any,
    *,
    mode: RunMode,
    target: Callable[[str, Any, Any, Any | None], None],
) -> threading.Thread:
    worker = threading.Thread(
        target=target,
        args=(task_id, gateway, event, current_event_loop_or_none()),
        name=f"coding-{_thread_label_for_mode(mode)}-{task_id}",
        daemon=True,
    )
    worker.start()
    return worker


def run_and_notify(
    task_id: str,
    gateway: Any,
    event: Any,
    loop: Any | None,
    *,
    mode: RunMode,
    execute: Callable[[], dict[str, Any]],
    format_success_message: Callable[[dict[str, Any]], str],
    mark_failed: Callable[[Exception], None],
    record_notification: Callable[[dict[str, Any], dict[str, Any]], None],
    after_success: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    result: dict[str, Any] = {}
    try:
        result = execute()
        if after_success is not None:
            after_success(result)
        message = format_success_message(result)
    except Exception as exc:
        mark_failed(exc)
        message = failure_message(task_id, mode, exc)
    reply = reply_if_possible(gateway, event, message, loop=loop)
    record_notification(result, reply)


def failure_message(task_id: str, mode: RunMode, exc: Exception) -> str:
    mode_label = {
        RunMode.PLAN_ONLY: "计划",
        RunMode.IMPLEMENTATION: "实现",
        RunMode.QA: "QA",
        RunMode.MERGE_TEST: "merge-test",
    }.get(mode, mode.value)
    return f"[{task_id}] {mode_label}执行失败：{exc}\n请查看任务详情和执行日志后重试。"


def completion_notification_record(
    *,
    mode: RunMode,
    result: dict[str, Any],
    reply: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, str]:
    timestamp = now or datetime.now(timezone.utc)
    return {
        "status": str(reply.get("status") or "unknown"),
        "mode": mode.value,
        "run_id": str(result.get("run_id") or ""),
        "task_status": str(result.get("task_status") or ""),
        "reason": str(reply.get("reason") or ""),
        "channel": str(reply.get("channel") or ""),
        "updated_at": timestamp.isoformat(),
    }


def record_completion_notification(
    ledger: Any,
    task_id: str,
    *,
    mode: RunMode,
    result: dict[str, Any],
    reply: dict[str, Any],
) -> None:
    try:
        ledger.update_task_session(
            task_id,
            {"last_completion_notification": completion_notification_record(mode=mode, result=result, reply=reply)},
        )
    except Exception:
        pass


async def call_sender(sender: Any, *args: Any) -> None:
    result = sender(*args)
    if inspect.isawaitable(result):
        await result


def schedule_sender(sender: Any, args: tuple[Any, ...], loop: Any | None) -> dict[str, str]:
    if loop is not None and getattr(loop, "is_running", lambda: False)():
        future = asyncio.run_coroutine_threadsafe(call_sender(sender, *args), loop)
        try:
            future.result(timeout=15)
        except Exception as exc:
            return {
                "status": "failed",
                "reason": f"{exc.__class__.__name__}: {exc}",
            }
        return {"status": "ok"}

    discovered_loop = None
    if loop is None:
        discovered_loop = current_event_loop_or_none()
    if discovered_loop is not None and getattr(discovered_loop, "is_running", lambda: False)():
        discovered_loop.call_soon_threadsafe(lambda: asyncio.create_task(call_sender(sender, *args)))
        return {"status": "scheduled", "reason": "scheduled_on_current_event_loop"}
    try:
        asyncio.run(call_sender(sender, *args))
    except RuntimeError as exc:
        if "asyncio.run() cannot be called from a running event loop" not in str(exc):
            return {
                "status": "failed",
                "reason": f"{exc.__class__.__name__}: {exc}",
            }
        try:
            result = sender(*args)
        except Exception as send_exc:
            return {
                "status": "failed",
                "reason": f"{send_exc.__class__.__name__}: {send_exc}",
            }
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            return {
                "status": "failed",
                "reason": f"{exc.__class__.__name__}: awaitable sender could not be awaited",
            }
        return {"status": "ok"}
    except Exception as exc:
        return {
            "status": "failed",
            "reason": f"{exc.__class__.__name__}: {exc}",
        }
    return {"status": "ok"}


def reply_if_possible(gateway: Any, event: Any, message: str, *, loop: Any | None = None) -> dict[str, str]:
    sender = getattr(gateway, "send_message", None)
    if callable(sender):
        try:
            result = schedule_sender(sender, (getattr(event, "source", None), message), loop)
        except Exception as exc:
            result = {"status": "failed", "reason": f"{exc.__class__.__name__}: {exc}"}
        return {**result, "channel": "gateway.send_message"}
    source = getattr(event, "source", None)
    adapters = getattr(gateway, "adapters", {}) if gateway is not None else {}
    adapter = adapters.get(getattr(source, "platform", None)) if isinstance(adapters, dict) else None
    chat_id = getattr(source, "chat_id", None)
    send = getattr(adapter, "send", None)
    if not callable(send) or not chat_id:
        return {"status": "skipped", "reason": "gateway_sender_unavailable", "channel": ""}
    try:
        result = schedule_sender(send, (chat_id, message), loop)
    except Exception as exc:
        result = {"status": "failed", "reason": f"{exc.__class__.__name__}: {exc}"}
    return {**result, "channel": "adapter.send"}


def _thread_label_for_mode(mode: RunMode) -> str:
    return {
        RunMode.PLAN_ONLY: "plan",
        RunMode.IMPLEMENTATION: "implementation",
        RunMode.QA: "qa",
        RunMode.MERGE_TEST: "merge-test",
    }.get(mode, mode.value)
