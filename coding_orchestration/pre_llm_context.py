from __future__ import annotations

from typing import Any


def build_pre_llm_context(orchestrator: Any, *, session_id: str, platform: str) -> str:
    active_task_id = orchestrator.active_task_for_session(session_id=session_id, platform=platform)
    if not active_task_id:
        return ""
    status = orchestrator._task_status_payload(active_task_id)
    if not status.get("ok"):
        return ""
    next_actions = status.get("next_actions") or []
    lines = [
        "Hermes Coding Context",
        f"- active_task: {active_task_id}",
        f"- task_status: {status.get('status') or 'unknown'}",
        f"- task_phase: {status.get('phase') or 'unknown'}",
        f"- source_status: {status.get('source_status') or 'unknown'}",
        f"- source_type: {status.get('source_type') or 'unknown'}",
        f"- project_name: {status.get('project_name') or ''}",
        f"- project_path: {status.get('project_path') or ''}",
        f"- runner: {status.get('runner') or ''}",
        f"- next_actions: {', '.join(str(action) for action in next_actions)}",
        "- preferred_tools: coding_task_status, coding_source_resolve, coding_lark_preflight, coding_task_run",
        "- coding_task_run modes: plan-only, implementation, qa, merge-test; QA is optional and must be explicitly requested.",
        "- rule: source/auth problems are not hard blocked unless human input is strictly required.",
    ]
    return "\n".join(lines)
