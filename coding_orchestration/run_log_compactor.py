from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


MAX_OUTPUT_CHARS = 900


def compact_run_logs(run_dir: Path) -> dict[str, Any]:
    """Create compact operator-facing logs from raw Codex stdout/stderr.

    Raw ``stdout.log`` and ``stderr.log`` remain untouched. This post-processing
    layer gives Hermes and humans a small default view while preserving full
    evidence for deep debugging and report recovery.
    """

    run_dir = run_dir.expanduser()
    manifest = _read_json(run_dir / "run-manifest.json")
    report = _read_json(run_dir / "report.json")
    stdout_events = _read_stdout_events(run_dir / "stdout.log")
    stderr_lines = _read_lines(run_dir / "stderr.log")

    commands = _command_events(stdout_events)
    messages = _agent_messages(stdout_events)
    todos = _todo_events(stdout_events)
    stderr_counter = Counter(line for line in stderr_lines if line.strip())

    compact_events = _compact_events(
        manifest=manifest,
        report=report,
        commands=commands,
        messages=messages,
        todos=todos,
        stderr_counter=stderr_counter,
    )
    compact_path = run_dir / "events.compact.jsonl"
    compact_path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in compact_events) + ("\n" if compact_events else ""),
        encoding="utf-8",
    )

    markdown_path = run_dir / "run-log.md"
    markdown_path.write_text(
        _render_markdown(
            manifest=manifest,
            report=report,
            commands=commands,
            messages=messages,
            todos=todos,
            stderr_counter=stderr_counter,
        ),
        encoding="utf-8",
    )

    folded_messages = sum(count - 1 for count in Counter(messages).values() if count > 1)
    folded_stderr = sum(count - 1 for count in stderr_counter.values() if count > 1)
    return {
        "compact_events": str(compact_path),
        "operator_log": str(markdown_path),
        "commands": len(commands),
        "messages": len(messages),
        "folded_messages": folded_messages,
        "folded_stderr": folded_stderr,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _read_stdout_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in _read_lines(path):
        try:
            value = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _command_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "command_execution":
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        output = str(item.get("aggregated_output") or item.get("output") or "")
        exit_code = item.get("exit_code")
        status = str(item.get("status") or event.get("type") or "")
        commands.append(
            {
                "command": command,
                "exit_code": exit_code,
                "status": status,
                "output": output,
            }
        )
    return commands


def _agent_messages(events: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for event in events:
        text = _event_text(event).strip()
        if text:
            messages.append(text)
    return messages


def _todo_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    todos: list[dict[str, Any]] = []
    for event in events:
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "todo_list":
            todos.append(item)
    return todos


def _event_text(event: dict[str, Any]) -> str:
    for key in ("message", "text", "content", "delta"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    item = event.get("item")
    if isinstance(item, dict):
        for key in ("text", "message", "content"):
            value = item.get(key)
            if isinstance(value, str):
                return value
    return ""


def _compact_events(
    *,
    manifest: dict[str, Any],
    report: dict[str, Any],
    commands: list[dict[str, Any]],
    messages: list[str],
    todos: list[dict[str, Any]],
    stderr_counter: Counter[str],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {
            "type": "run",
            "run_id": manifest.get("run_id"),
            "mode": manifest.get("mode") or report.get("mode"),
            "status": report.get("status"),
        }
    ]
    message_counter = Counter(messages)
    for message, count in message_counter.items():
        events.append({"type": "agent_message", "text": message, "count": count})
    for command in commands:
        events.append(
            {
                "type": "command",
                "command": command["command"],
                "exit_code": command.get("exit_code"),
                "status": command.get("status"),
                "output_summary": _output_summary(command.get("output") or ""),
            }
        )
    if todos:
        events.append({"type": "todo_list", "items": todos[-1].get("items") or []})
    for line, count in stderr_counter.items():
        events.append({"type": "stderr", "text": line, "count": count})
    return events


def _render_markdown(
    *,
    manifest: dict[str, Any],
    report: dict[str, Any],
    commands: list[dict[str, Any]],
    messages: list[str],
    todos: list[dict[str, Any]],
    stderr_counter: Counter[str],
) -> str:
    lines = [
        "# Run Log",
        "",
        "## Overview",
        "",
        f"- Run: `{manifest.get('run_id') or '-'}`",
        f"- Mode: `{manifest.get('mode') or report.get('mode') or '-'}`",
        f"- Status: `{report.get('status') or '-'}`",
    ]
    duration = manifest.get("duration_ms")
    if duration is not None:
        lines.append(f"- Duration: `{duration}ms`")
    if report.get("summary_markdown"):
        lines.extend(["", "## Summary", "", str(report.get("summary_markdown")).strip()])

    message_counter = Counter(messages)
    repeated = sum(count - 1 for count in message_counter.values() if count > 1)
    if message_counter:
        lines.extend(["", "## Agent Messages", ""])
        for message, count in message_counter.items():
            suffix = f"（重复 {count} 次）" if count > 1 else ""
            lines.append(f"- {message}{suffix}")
        if repeated:
            lines.append(f"- 重复消息已折叠：{repeated} 条")

    if commands:
        lines.extend(["", "## Commands", ""])
        for command in commands:
            exit_code = command.get("exit_code")
            status = "PASS" if exit_code in (0, "0", None) else "FAIL"
            lines.append(f"- {status} `{command['command']}`")
            output_summary = _output_summary(command.get("output") or "")
            if output_summary:
                lines.append(f"  - {output_summary}")

    if todos:
        lines.extend(["", "## Latest Todo State", ""])
        for item in todos[-1].get("items") or []:
            if not isinstance(item, dict):
                continue
            marker = "done" if item.get("completed") else "pending"
            lines.append(f"- {marker}: {item.get('text') or ''}")

    if stderr_counter:
        folded = sum(count - 1 for count in stderr_counter.values() if count > 1)
        lines.extend(["", "## Stderr", ""])
        for line, count in stderr_counter.items():
            suffix = f"（重复 {count} 次）" if count > 1 else ""
            lines.append(f"- {line[:300]}{suffix}")
        if folded:
            lines.append(f"- stderr 重复行已折叠：{folded} 条")

    risks = report.get("risks") if isinstance(report.get("risks"), list) else []
    if risks:
        lines.extend(["", "## Risks", ""])
        lines.extend(f"- {risk}" for risk in risks)

    limitations = report.get("verification_limitations") if isinstance(report.get("verification_limitations"), list) else []
    if limitations:
        lines.extend(["", "## Verification Limitations", ""])
        for item in limitations:
            if isinstance(item, dict):
                lines.append(f"- {item.get('reason') or '-'}: {item.get('impact') or ''}")

    return "\n".join(lines).rstrip() + "\n"


def _output_summary(output: str) -> str:
    value = output.strip()
    if not value:
        return ""
    if len(value) <= MAX_OUTPUT_CHARS:
        return value.replace("\n", " ")[:MAX_OUTPUT_CHARS]
    head = value[:450].strip().replace("\n", " ")
    tail = value[-250:].strip().replace("\n", " ")
    return f"输出已折叠：{len(value)} chars；开头：{head}；结尾：{tail}"
