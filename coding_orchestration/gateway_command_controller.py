from __future__ import annotations

import re
import time
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass
from typing import Any

from .project_resolver import normalize_text as normalize_project_text


CODING_COMMAND_RE = re.compile(r"^\s*/(coding)(?:\s+(.*)|\s*)$", re.I | re.S)
COMMANDS_COMMAND_RE = re.compile(r"^\s*/commands\b\s*(.*)$", re.I | re.S)
CODING_MODE_ENTER_RE = re.compile(r"^\s*进入\s*cod(?:e|ing)(?:\s*mode|模式)?\s*$", re.I)
CODING_MODE_EXIT_RE = re.compile(r"^\s*退出\s*cod(?:e|ing)(?:\s*mode|模式)?\s*$", re.I)
GATEWAY_EVENT_DEDUPE_WINDOW_SECONDS = 300
TASK_ID_SOURCE_NONE = "none"
TASK_ID_SOURCE_RAW = "raw"
TASK_ID_SOURCE_RAW_OR_ACTIVE = "raw_or_active"
TASK_ID_SOURCE_MERGE_TEST_ARGS = "merge_test_args"
GATEWAY_REPLY_IMMEDIATE = "immediate_reply"
GATEWAY_REPLY_CUSTOM = "custom"
CANONICAL_ACTION_BY_INTERNAL_COMMAND = {
    "coding-help": "help",
    "coding-task": "task",
    "coding-list": "list",
    "coding-project-list": "project list",
    "coding-project-init": "project init",
    "coding-project-use": "project use",
    "coding-project-status": "project status",
    "coding-project-clear": "project clear",
    "coding-use": "use",
    "coding-exit": "exit",
    "coding-status": "status",
    "coding-continue": "continue",
    "coding-change": "change",
    "coding-bugfix": "bugfix",
    "coding-run": "run",
    "coding-implement": "implement",
    "coding-qa": "qa",
    "coding-cancel": "cancel",
    "coding-delete": "delete",
    "coding-prepare-merge-test": "prepare-merge-test",
    "coding-merge-test": "merge-test",
    "coding-complete": "complete",
    "coding-restore": "restore",
}
COMMAND_ROUTE_SPECS = {
    "coding-help": ("help", TASK_ID_SOURCE_NONE, "help", GATEWAY_REPLY_IMMEDIATE),
    "coding-doctor": ("diagnostic", TASK_ID_SOURCE_NONE, "doctor", GATEWAY_REPLY_IMMEDIATE),
    "coding-lark-preflight": ("diagnostic", TASK_ID_SOURCE_NONE, "lark_preflight", GATEWAY_REPLY_IMMEDIATE),
    "coding-project-mcp-preflight": (
        "diagnostic",
        TASK_ID_SOURCE_NONE,
        "project_mcp_preflight",
        GATEWAY_REPLY_IMMEDIATE,
    ),
    "coding-source-resolve": ("diagnostic", TASK_ID_SOURCE_RAW, "source_resolve", GATEWAY_REPLY_IMMEDIATE),
    "coding-task": ("task_creation", TASK_ID_SOURCE_NONE, "create_task", GATEWAY_REPLY_CUSTOM),
    "coding-list": ("task_listing", TASK_ID_SOURCE_NONE, "list", GATEWAY_REPLY_IMMEDIATE),
    "coding-project-list": ("project_context", TASK_ID_SOURCE_NONE, "project_list", GATEWAY_REPLY_IMMEDIATE),
    "coding-project-init": ("project_context", TASK_ID_SOURCE_RAW, "project_init", GATEWAY_REPLY_IMMEDIATE),
    "coding-project-use": ("project_context", TASK_ID_SOURCE_RAW, "project_use", GATEWAY_REPLY_IMMEDIATE),
    "coding-project-status": ("project_context", TASK_ID_SOURCE_NONE, "project_status", GATEWAY_REPLY_IMMEDIATE),
    "coding-project-clear": ("project_context", TASK_ID_SOURCE_NONE, "project_clear", GATEWAY_REPLY_IMMEDIATE),
    "coding-use": ("session_binding", TASK_ID_SOURCE_RAW, "use", GATEWAY_REPLY_IMMEDIATE),
    "coding-exit": ("session_binding", TASK_ID_SOURCE_NONE, "exit", GATEWAY_REPLY_IMMEDIATE),
    "coding-status": ("task_status", TASK_ID_SOURCE_RAW_OR_ACTIVE, "status", GATEWAY_REPLY_IMMEDIATE),
    "coding-continue": ("task_feedback", TASK_ID_SOURCE_NONE, "continue", GATEWAY_REPLY_CUSTOM),
    "coding-change": ("task_feedback", TASK_ID_SOURCE_NONE, "change", GATEWAY_REPLY_CUSTOM),
    "coding-bugfix": ("task_feedback", TASK_ID_SOURCE_NONE, "bugfix", GATEWAY_REPLY_CUSTOM),
    "coding-run": ("plan_run", TASK_ID_SOURCE_RAW_OR_ACTIVE, "run", GATEWAY_REPLY_CUSTOM),
    "coding-analyze": ("delivery", TASK_ID_SOURCE_RAW_OR_ACTIVE, "analyze", GATEWAY_REPLY_CUSTOM),
    "coding-breakdown": ("delivery", TASK_ID_SOURCE_RAW_OR_ACTIVE, "breakdown", GATEWAY_REPLY_CUSTOM),
    "coding-approve-breakdown": (
        "delivery",
        TASK_ID_SOURCE_RAW_OR_ACTIVE,
        "approve_breakdown",
        GATEWAY_REPLY_CUSTOM,
    ),
    "coding-materialize": ("delivery", TASK_ID_SOURCE_RAW_OR_ACTIVE, "materialize", GATEWAY_REPLY_CUSTOM),
    "coding-implement": ("implementation_run", TASK_ID_SOURCE_RAW_OR_ACTIVE, "implement", GATEWAY_REPLY_CUSTOM),
    "coding-qa": ("qa_run", TASK_ID_SOURCE_RAW_OR_ACTIVE, "qa", GATEWAY_REPLY_CUSTOM),
    "coding-prepare-merge-test": (
        "merge_test_prepare",
        TASK_ID_SOURCE_RAW_OR_ACTIVE,
        "prepare_merge_test",
        GATEWAY_REPLY_CUSTOM,
    ),
    "coding-merge-test": ("merge_test_run", TASK_ID_SOURCE_MERGE_TEST_ARGS, "merge_test", GATEWAY_REPLY_CUSTOM),
    "coding-complete": ("task_completion", TASK_ID_SOURCE_RAW_OR_ACTIVE, "complete", GATEWAY_REPLY_IMMEDIATE),
    "coding-cancel": ("task_lifecycle", TASK_ID_SOURCE_RAW, "cancel", GATEWAY_REPLY_IMMEDIATE),
    "coding-restore": ("task_lifecycle", TASK_ID_SOURCE_RAW, "restore", GATEWAY_REPLY_IMMEDIATE),
    "coding-delete": ("task_lifecycle", TASK_ID_SOURCE_RAW, "delete", GATEWAY_REPLY_IMMEDIATE),
}


@dataclass(frozen=True)
class CodingGatewayCommand:
    command: str
    raw_args: str


@dataclass(frozen=True)
class CommandsGatewayCommand:
    raw_args: str


@dataclass(frozen=True)
class GatewayCommandRoute:
    command: str
    raw_args: str
    family: str
    task_id_source: str = TASK_ID_SOURCE_NONE
    handler_key: str = ""
    reply_mode: str = GATEWAY_REPLY_CUSTOM
    clears_pending_action: bool = True

    @property
    def uses_active_task_fallback(self) -> bool:
        return self.task_id_source in {TASK_ID_SOURCE_RAW_OR_ACTIVE, TASK_ID_SOURCE_MERGE_TEST_ARGS}


@dataclass(frozen=True)
class MergeTestCommandArgs:
    task_id: str
    accept_risk: bool
    confirm_qa_risk: bool


def parse_coding_gateway_command(text: str) -> CodingGatewayCommand | None:
    match = CODING_COMMAND_RE.match(normalize_project_text(text))
    if not match:
        return None
    command = match.group(1).lower()
    raw_args = (match.group(2) or "").strip()
    command, raw_args = normalize_coding_gateway_command(command, raw_args)
    return CodingGatewayCommand(command=command, raw_args=raw_args)


def parse_commands_gateway_command(text: str) -> CommandsGatewayCommand | None:
    match = COMMANDS_COMMAND_RE.match(normalize_project_text(text))
    if not match:
        return None
    return CommandsGatewayCommand(raw_args=match.group(1).strip())


def route_coding_gateway_command(text: str) -> GatewayCommandRoute | None:
    parsed = parse_coding_gateway_command(text)
    if parsed is None:
        return None
    family, task_id_source, handler_key, reply_mode = COMMAND_ROUTE_SPECS.get(
        parsed.command,
        ("unknown", TASK_ID_SOURCE_NONE, "unknown", GATEWAY_REPLY_CUSTOM),
    )
    return GatewayCommandRoute(
        command=parsed.command,
        raw_args=parsed.raw_args,
        family=family,
        task_id_source=task_id_source,
        handler_key=handler_key,
        reply_mode=reply_mode,
    )


def gateway_route_task_id(route: GatewayCommandRoute, active_task_id: str | None = None) -> str:
    active = str(active_task_id or "").strip()
    if route.task_id_source == TASK_ID_SOURCE_RAW:
        return route.raw_args.strip()
    if route.task_id_source == TASK_ID_SOURCE_RAW_OR_ACTIVE:
        return route.raw_args.strip() or active
    if route.task_id_source == TASK_ID_SOURCE_MERGE_TEST_ARGS:
        return parse_merge_test_command_args(route.raw_args, active).task_id
    return ""


def normalize_coding_gateway_command(command: str, raw_args: str) -> tuple[str, str]:
    if command == "coding-help":
        return "coding-help", raw_args
    if command != "coding":
        return command, raw_args
    action, _, rest = raw_args.strip().partition(" ")
    action = action.strip().lower()
    rest = rest.strip()
    if action in {"", "help", "-help", "--help"}:
        return "coding-help", rest
    if action == "project":
        project_action, _, project_rest = rest.partition(" ")
        project_action = project_action.strip().lower()
        project_rest = project_rest.strip()
        project_map = {
            "list": "coding-project-list",
            "init": "coding-project-init",
            "use": "coding-project-use",
            "status": "coding-project-status",
            "clear": "coding-project-clear",
        }
        if not project_action:
            return "coding-project-status", ""
        mapped_project = project_map.get(project_action)
        if mapped_project:
            return mapped_project, project_rest
        return "coding-help", raw_args
    command_map = {
        "task": "coding-task",
        "new": "coding-task",
        "create": "coding-task",
        "doctor": "coding-doctor",
        "lark-preflight": "coding-lark-preflight",
        "project-mcp-preflight": "coding-project-mcp-preflight",
        "source-resolve": "coding-source-resolve",
        "status": "coding-status",
        "list": "coding-list",
        "use": "coding-use",
        "exit": "coding-exit",
        "continue": "coding-continue",
        "change": "coding-change",
        "revise": "coding-change",
        "bugfix": "coding-bugfix",
        "run": "coding-run",
        "analyze": "coding-analyze",
        "breakdown": "coding-breakdown",
        "approve-breakdown": "coding-approve-breakdown",
        "materialize": "coding-materialize",
        "implement": "coding-implement",
        "qa": "coding-qa",
        "test": "coding-qa",
        "cancel": "coding-cancel",
        "restore": "coding-restore",
        "reopen": "coding-restore",
        "delete": "coding-delete",
        "prepare-merge-test": "coding-prepare-merge-test",
        "merge-test": "coding-merge-test",
        "complete": "coding-complete",
    }
    mapped = command_map.get(action)
    if mapped:
        return mapped, rest
    return "coding-help", raw_args


def parse_merge_test_command_args(raw_args: str, active_task_id: str | None = None) -> MergeTestCommandArgs:
    args = raw_args.split()
    accept_risk = "--accept-risk" in args
    confirm_qa_risk = "--confirm-qa-risk" in args or accept_risk
    task_id = next((part for part in args if not part.startswith("--")), "") or str(active_task_id or "").strip()
    return MergeTestCommandArgs(
        task_id=task_id,
        accept_risk=accept_risk,
        confirm_qa_risk=confirm_qa_risk,
    )


def canonical_rewrite_command(value: Any, allowed_actions: Iterable[str]) -> str:
    if not isinstance(value, str):
        return ""
    command_text = normalize_project_text(value)
    match = CODING_COMMAND_RE.match(command_text)
    if not match:
        return ""
    raw_args = (match.group(2) or "").strip()
    action, _, _rest = raw_args.partition(" ")
    action = action.strip().lower()
    if action not in set(allowed_actions):
        return ""
    parsed = parse_coding_gateway_command(command_text)
    if parsed is None:
        return ""
    canonical_action = CANONICAL_ACTION_BY_INTERNAL_COMMAND.get(parsed.command)
    if canonical_action is None:
        return ""
    return f"/coding {canonical_action}{f' {parsed.raw_args}' if parsed.raw_args else ''}".strip()


def rewrite_requires_confirmation(command_text: str, rewrite: dict[str, Any]) -> bool:
    if bool(rewrite.get("needs_confirmation")):
        return True
    risk_level = str(rewrite.get("risk_level") or "").strip().lower()
    if risk_level == "destructive":
        return True
    normalized = normalize_project_text(command_text).lower()
    return normalized.startswith("/coding delete ") or normalized.startswith("/coding cancel ")


def is_rewrite_confirmation(text: str) -> bool:
    value = normalize_project_text(text).lower()
    return value in {"确认", "确认执行", "执行", "可以", "可以执行", "好的", "好", "ok", "okay", "yes", "y"}


def is_rewrite_cancellation(text: str) -> bool:
    value = normalize_project_text(text).lower()
    return value in {"取消", "取消执行", "放弃", "不要执行", "不执行", "算了", "no", "n"}


def is_human_confirmation_reply(text: str) -> bool:
    value = normalize_project_text(text).lower()
    if not value or is_human_cancellation_reply(value):
        return False
    if value in {"确认", "确认执行", "执行", "可以", "可以执行", "好的", "好", "ok", "okay", "yes", "y", "继续", "确认继续"}:
        return True
    confirmation_markers = ("确认", "确定", "可以", "同意", "继续", "执行", "提交")
    return len(value) <= 80 and any(marker in value for marker in confirmation_markers)


def is_human_cancellation_reply(text: str) -> bool:
    value = normalize_project_text(text).lower()
    if value in {"取消", "取消执行", "放弃", "不要执行", "不执行", "算了", "no", "n", "先别", "暂停"}:
        return True
    cancellation_markers = ("取消", "放弃", "不要", "不可以", "别", "暂停")
    return len(value) <= 80 and any(marker in value for marker in cancellation_markers)


def looks_like_plugin_generated_message(text: str) -> bool:
    return bool(re.search(r"^\s*\[task_[A-Za-z0-9_:-]+\]", normalize_project_text(text)))


def looks_like_task(text: str) -> bool:
    value = normalize_project_text(text)
    return bool(
        CODING_COMMAND_RE.match(value)
        or CODING_MODE_ENTER_RE.match(value)
        or CODING_MODE_EXIT_RE.match(value)
    )


def gateway_event_dedupe_key(event: Any) -> str | None:
    message_id = str(
        getattr(event, "message_id", None)
        or getattr(getattr(event, "source", None), "message_id", None)
        or ""
    ).strip()
    if not message_id:
        return None
    source = getattr(event, "source", None)
    platform = getattr(source, "platform", "") if source is not None else ""
    platform_value = getattr(platform, "value", platform)
    chat_id = getattr(source, "chat_id", "") if source is not None else ""
    user_id = getattr(source, "user_id", "") if source is not None else ""
    return f"{platform_value}:{chat_id}:{user_id}:{message_id}"


def dedupe_gateway_event(
    recent_gateway_event_ids: MutableMapping[str, float],
    event: Any,
    *,
    now: float | None = None,
    window_seconds: int = GATEWAY_EVENT_DEDUPE_WINDOW_SECONDS,
) -> dict[str, str] | None:
    key = gateway_event_dedupe_key(event)
    if not key:
        return None
    current = time.monotonic() if now is None else now
    cutoff = current - window_seconds
    stale_keys = [item for item, seen_at in recent_gateway_event_ids.items() if seen_at < cutoff]
    for item in stale_keys:
        recent_gateway_event_ids.pop(item, None)
    if key in recent_gateway_event_ids:
        return {"action": "skip", "reason": "duplicate_gateway_event"}
    recent_gateway_event_ids[key] = current
    return None


def gateway_user_is_authorized(gateway: Any, event: Any) -> bool:
    checker = getattr(gateway, "_is_user_authorized", None)
    source = getattr(event, "source", None)
    if not callable(checker) or source is None or getattr(source, "user_id", None) is None:
        return True
    try:
        return bool(checker(source))
    except Exception:
        return True
