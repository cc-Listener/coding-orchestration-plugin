from __future__ import annotations

from typing import Any


def source_block(source: dict[str, Any]) -> str:
    allowed_keys = ("type", "title", "url", "project_name", "message_summary", "related_task_id")
    lines = [f"- {key}: {source[key]}" for key in allowed_keys if source.get(key)]
    source_context = source.get("source_context")
    if isinstance(source_context, dict) and source_context:
        context_lines = _source_context_lines(source_context)
        if context_lines:
            lines.append("- 外部来源上下文：")
            lines.extend(context_lines)
    return "\n".join(lines) or "- 未记录"


def truncate_source_context_value(value: str, limit: int = 2000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n      ...（已截断）"


def _source_context_lines(source_context: dict[str, Any]) -> list[str]:
    context_keys = (
        "read_status",
        "source_type",
        "url",
        "document_kind",
        "document_token",
        "project_key",
        "work_item_type_key",
        "work_item_id",
        "resolution_owner",
        "deferred_source_resolution",
        "error",
    )
    context_lines = [
        f"  - {key}: {source_context[key]}"
        for key in context_keys
        if source_context.get(key)
    ]
    command = str(source_context.get("lark_cli_command") or "").strip()
    if command:
        context_lines.append(f"  - lark_cli_command: `{command}`")
    raw_fields = source_context.get("raw_fields")
    if isinstance(raw_fields, list):
        context_lines.extend(_raw_field_lines(raw_fields))
    if source_context.get("codex_resolvable"):
        context_lines.append("  - note: 来源正文未注入；请优先在本 Codex session 中使用 lark_cli_command 读取。读取失败时按 recovery_action 报告恢复方案。")
    elif source_context.get("deferred_source_resolution"):
        context_lines.append("  - note: 来源正文未注入；不要猜测文档内容。若无法在当前环境读取，按 recovery_action 要求补充。")
    return context_lines


def _raw_field_lines(raw_fields: list[Any]) -> list[str]:
    lines = ["  - raw_fields:"]
    rendered_fields = False
    if raw_fields:
        for field in raw_fields[:50]:
            if isinstance(field, dict):
                name = str(field.get("name") or "").strip()
                value = truncate_source_context_value(str(field.get("value") or ""))
                if not name and not value:
                    continue
                lines.append(f"    - {name}: {value}")
                rendered_fields = True
    if not rendered_fields:
        lines.append("    - 未返回可用字段。")
    return lines

