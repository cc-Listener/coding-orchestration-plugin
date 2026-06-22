from __future__ import annotations

import re
from typing import Any

from .command_catalog import (
    allowed_rewrite_commands,
    allowed_top_level_actions,
    command_catalog_context,
)
from .project_resolver import normalize_text as normalize_project_text
from . import gateway_command_controller, gateway_rewrite_context, gateway_rewrite_presenter, run_start_presenter


_CODING_MODE_ENTER_RE = gateway_command_controller.CODING_MODE_ENTER_RE
_CODING_MODE_EXIT_RE = gateway_command_controller.CODING_MODE_EXIT_RE
_CODING_REWRITE_CONFIDENCE_THRESHOLD = 0.85
_RECOMMENDED_OPERATOR_SKILL = "coding_orchestration:hermes-coding-operator"


def handle_coding_mode_gateway_message(host: Any, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
    normalized = normalize_project_text(text)
    if _CODING_MODE_ENTER_RE.match(normalized):
        already_enabled = host._coding_mode_enabled_for_event(event)
        host._enable_coding_mode_for_event(event)
        host._clear_pending_rewrite_for_event(event)
        host._clear_pending_action_for_event(event)
        message = (
            "当前已在 coding mode。本会话自然语言会按 coding 指令处理；发送“退出coding”关闭。"
            if already_enabled
            else "已进入 coding mode。本会话后续自然语言会按 coding 指令处理；发送“退出coding”关闭。"
        )
        host._reply_if_possible(gateway, event, message)
        return {"action": "skip", "reason": "coding_mode_entered"}
    if _CODING_MODE_EXIT_RE.match(normalized):
        was_enabled = host._coding_mode_enabled_for_event(event)
        host._disable_coding_mode_for_event(event)
        host._clear_pending_rewrite_for_event(event)
        host._clear_pending_action_for_event(event)
        message = (
            "已退出 coding mode。本会话后续自然语言不会再按开发任务指令处理。"
            if was_enabled
            else "当前未开启 coding mode。本会话自然语言不会自动创建或推进开发任务。"
        )
        host._reply_if_possible(gateway, event, message)
        return {"action": "skip", "reason": "coding_mode_exited"}
    if not host._coding_mode_enabled_for_event(event):
        return None
    if host._looks_like_plugin_generated_message(normalized):
        return {"action": "skip", "reason": "ignored_coding_orchestration_echo"}

    pending_action = host._handle_pending_action_gateway_message(
        normalized,
        event,
        gateway,
        include_latest_human_required=True,
    )
    if pending_action is not None:
        return pending_action
    if host._is_human_confirmation_reply(normalized):
        active_task = host._active_task_for_event(event)
        if active_task and host._task_has_active_run(active_task):
            host._reply_if_possible(gateway, event, run_start_presenter.active_run_already_running_message(active_task))
            return {"action": "skip", "reason": "coding_confirmation_active_run"}

    pending = host._pending_rewrite_for_event(event)
    if pending:
        if host._is_rewrite_confirmation(normalized):
            host._clear_pending_rewrite_for_event(event)
            command_text = str(pending.get("canonical_command") or "").strip()
            handled = host._handle_explicit_gateway_command(command_text, event, gateway)
            if handled is None:
                host._reply_if_possible(
                    gateway,
                    event,
                    f"未执行：待确认的 rewrite 命令已失效。\n候选命令：{command_text or '无'}\n请重新描述或直接发送 /coding <action>。",
                )
            return {"action": "skip", "reason": "coding_rewrite_confirmed"}
        if host._is_rewrite_cancellation(normalized):
            host._clear_pending_rewrite_for_event(event)
            host._reply_if_possible(gateway, event, "已取消本次 coding rewrite 候选命令，未执行任何操作。")
            return {"action": "skip", "reason": "coding_rewrite_cancelled"}
        host._clear_pending_rewrite_for_event(event)

    if host.command_rewriter is None:
        return handoff_rewrite_to_hermes(
            host,
            normalized,
            event,
            {
                "intent": "llm_unavailable",
                "canonical_command": None,
                "confidence": 0.0,
                "risk_level": "unknown",
                "needs_confirmation": False,
                "needs_human_review": True,
                "missing": ["command_rewriter"],
                "reason": "当前 coding mode 未配置 command_rewriter。",
            },
            "当前 coding mode 未配置 command_rewriter。",
        )

    rewrite = rewrite_coding_command(host, normalized, event)
    command_text, rejection = validated_rewrite_command(rewrite)
    if rejection:
        return handoff_rewrite_to_hermes(host, normalized, event, rewrite, rejection)

    if rewrite_requires_confirmation(command_text, rewrite):
        host._store_pending_rewrite_for_event(event, command_text, rewrite, normalized)
        host._reply_if_possible(gateway, event, rewrite_confirmation_message(command_text, rewrite))
        return {"action": "skip", "reason": "coding_rewrite_confirmation"}

    handled = host._handle_explicit_gateway_command(command_text, event, gateway)
    if handled is None:
        host._reply_if_possible(
            gateway,
            event,
            f"未执行：rewrite 命令未被 `/coding` handler 接受。\n候选命令：{command_text}\n请直接发送明确的 /coding <action> 命令。",
        )
    return {"action": "skip", "reason": "coding_rewrite_executed"}


def handoff_rewrite_to_hermes(
    host: Any,
    text: str,
    event: Any,
    rewrite: dict[str, Any],
    rejection: str,
) -> dict[str, str]:
    return {
        "action": "rewrite",
        "reason": "coding_rewrite_handoff_to_hermes",
        "text": rewrite_handoff_to_hermes_message(host, text, rewrite, rejection, event),
    }


def extract_task_id(text: str) -> str:
    match = re.search(r"\btask_[A-Za-z0-9_:-]+\b", text)
    return match.group(0) if match else ""


def rewrite_coding_command(host: Any, text: str, event: Any) -> dict[str, Any]:
    context = coding_rewrite_context(host, text, event)
    try:
        result = host.command_rewriter.rewrite(context) if host.command_rewriter is not None else None
    except Exception as exc:
        return {
            "intent": "llm_error",
            "canonical_command": None,
            "confidence": 0.0,
            "risk_level": "unknown",
            "needs_confirmation": True,
            "needs_human_review": True,
            "task_id": None,
            "uses_active_task": False,
            "missing": ["canonical_command"],
            "reason": f"{type(exc).__name__}: {exc}",
        }
    if not isinstance(result, dict):
        return {
            "intent": "invalid_rewrite_result",
            "canonical_command": None,
            "confidence": 0.0,
            "risk_level": "unknown",
            "needs_confirmation": True,
            "needs_human_review": True,
            "task_id": None,
            "uses_active_task": False,
            "missing": ["canonical_command"],
            "reason": "command_rewriter 未返回 JSON object。",
        }
    return dict(result)


def coding_rewrite_context(host: Any, text: str, event: Any) -> dict[str, Any]:
    media = host._event_media_for_ledger(event)
    active_task = host._active_task_for_event(event)
    active_project = host._active_project_for_event(event)
    known_tasks = host.ledger.list_recent_tasks(statuses=host._active_coding_statuses(), limit=10)
    return gateway_rewrite_context.build_coding_rewrite_context(
        user_text=text,
        active_task=active_task,
        known_tasks=known_tasks,
        active_project=active_project,
        known_projects=host._known_project_profiles(limit=10),
        media=media,
        recommended_skill=_RECOMMENDED_OPERATOR_SKILL,
        command_catalog=command_catalog_context(),
        allowed_commands=coding_rewrite_allowed_commands(),
        project_label=host._task_project_label,
        summary_label=host._task_description_label,
    )


def task_next_step_hint(host: Any, task: dict[str, Any], event: Any | None) -> str:
    return gateway_rewrite_context.task_next_step_hint(
        task,
        has_active_project=bool(host._active_project_for_event(event)),
    )


def coding_rewrite_allowed_commands() -> list[dict[str, str]]:
    return allowed_rewrite_commands()


def validated_rewrite_command(rewrite: dict[str, Any]) -> tuple[str, str]:
    command_text = canonical_rewrite_command(rewrite.get("canonical_command"))
    if not command_text:
        return "", "LLM 没有返回合法的 `/coding <action>` 候选命令。"
    try:
        confidence = float(rewrite.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < _CODING_REWRITE_CONFIDENCE_THRESHOLD:
        return "", f"置信度 {confidence:.2f} 低于阈值 {_CODING_REWRITE_CONFIDENCE_THRESHOLD:.2f}。"
    if bool(rewrite.get("needs_human_review")):
        return "", "LLM 标记需要人工二次确认。"
    missing = rewrite.get("missing") or []
    if missing:
        return "", f"缺少必要信息：{', '.join(str(item) for item in missing)}。"
    return command_text, ""


def rewrite_requires_confirmation(command_text: str, rewrite: dict[str, Any]) -> bool:
    return gateway_command_controller.rewrite_requires_confirmation(command_text, rewrite)


def canonical_rewrite_command(value: Any) -> str:
    return gateway_command_controller.canonical_rewrite_command(value, allowed_top_level_actions())


def rewrite_confirmation_message(command_text: str, rewrite: dict[str, Any]) -> str:
    return gateway_rewrite_presenter.format_rewrite_confirmation_message(command_text, rewrite)


def rewrite_needs_human_confirmation_message(text: str, rewrite: dict[str, Any], rejection: str) -> str:
    return gateway_rewrite_presenter.format_rewrite_needs_human_confirmation_message(text, rewrite, rejection)


def rewrite_rejection_user_text(rejection: str) -> str:
    return gateway_rewrite_presenter.rewrite_rejection_user_text(rejection)


def rewrite_handoff_to_hermes_message(
    host: Any,
    text: str,
    rewrite: dict[str, Any],
    rejection: str,
    event: Any,
) -> str:
    del rewrite
    context = coding_rewrite_context(host, text, event)
    return gateway_rewrite_presenter.format_rewrite_handoff_to_hermes_message(text, context, rejection)
