from __future__ import annotations

from typing import Any


def render_user_update(
    *,
    title: str,
    task_id: str,
    user_facing_summary: str,
    next_actions: list[Any],
    risk_note: str = "",
    debug: dict[str, Any] | None = None,
) -> str:
    lines = [title, f"任务：{task_id}"]
    summary = user_facing_summary.strip()
    if summary:
        lines.extend(["", summary])

    risk = risk_note.strip()
    if risk:
        lines.extend(["", f"风险提示：{risk}"])

    actions = [_clean_text(item) for item in next_actions]
    actions = [item for item in actions if item]
    if actions:
        lines.extend(["", "下一步："])
        lines.extend(f"- {item}" for item in actions)

    debug_items = _render_debug_items(debug or {})
    if debug_items:
        lines.extend(["", "调试信息："])
        lines.extend(f"- {item}" for item in debug_items)

    return "\n".join(lines)


def _render_debug_items(debug: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for key, value in debug.items():
        rendered = _clean_text(value)
        if not rendered:
            continue
        items.append(f"{key}={rendered}")
    return items


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
