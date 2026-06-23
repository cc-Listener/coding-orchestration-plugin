from __future__ import annotations

from typing import Any

from ..command_catalog import command_help_lines, command_listing_lines


def command_coding_help(host: Any, raw_args: str = "") -> str:
    del host, raw_args
    return "\n".join(
        [
            "Coding Orchestration 命令帮助",
            "",
            *command_help_lines(),
            "",
            "边界",
            "- 默认普通自然语言不会自动创建开发任务；发送“进入coding”后，本会话自然语言会按 coding 指令处理，发送“退出coding”关闭。",
        ]
    )


def command_commands_listing(host: Any, raw_args: str = "") -> str:
    requested_page = 1
    raw_args = raw_args.strip()
    if raw_args:
        try:
            requested_page = int(raw_args)
        except ValueError:
            return "Usage: `/commands [page]`"

    entries = [
        "**Coding Orchestration Plugin Commands**:",
        *command_listing_lines(),
        "说明：默认普通自然语言不会自动创建开发任务；发送“进入coding”后，本会话自然语言会按 coding 指令处理。",
    ]
    hermes_lines = host._hermes_gateway_command_lines()
    if hermes_lines:
        entries.extend(["", "**Hermes Built-in Commands**:", *hermes_lines])

    page_size = 40
    total_pages = max(1, (len(entries) + page_size - 1) // page_size)
    page = max(1, min(requested_page, total_pages))
    start = (page - 1) * page_size
    page_entries = entries[start : start + page_size]
    lines = [
        f"**Commands** ({len(entries)} total, page {page}/{total_pages})",
        "",
        *page_entries,
    ]
    if total_pages > 1:
        nav_parts: list[str] = []
        if page > 1:
            nav_parts.append(f"prev: `/commands {page - 1}`")
        if page < total_pages:
            nav_parts.append(f"next: `/commands {page + 1}`")
        if nav_parts:
            lines.extend(["", " | ".join(nav_parts)])
    if page != requested_page:
        lines.append(f"_(Requested page {requested_page} was out of range, showing page {page}.)_")
    return "\n".join(lines)


def hermes_gateway_command_lines() -> list[str]:
    try:
        from hermes_cli.commands import gateway_help_lines

        return list(gateway_help_lines())
    except Exception:
        return []
